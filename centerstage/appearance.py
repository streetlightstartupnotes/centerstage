"""Conservative, non-biometric garment association; never a real-name recognizer.

Only shoulder-to-hip clothing patches are compared. No face embedding, head crop,
body-shape descriptor or external identity gallery is used. Similar outfits can
still be confused, so associations remain explicitly tentative and reversible.

Associations are revoked if any members of a group later occur together.
"""
from collections import Counter, deque
from time import perf_counter
import cv2
import numpy as np
from .config import get_config


def garment_descriptor(image, pose, other_poses=()):
    """提取服装描述符（肩部到臀部的颜色和纹理特征）"""
    pose = np.asarray(pose, dtype=np.float32)
    if pose.shape != (17, 3) or not np.isfinite(pose).all():
        return None
    core = pose[[5, 6, 12, 11]]
    if np.min(core[:, 2]) < 0.65:
        return None
    points = core[:, :2].copy()
    shoulder_y = max(points[0, 1], points[1, 1])
    hip_y = min(points[2, 1], points[3, 1])
    if hip_y - shoulder_y < 14 or abs(points[0, 0] - points[1, 0]) < 12:
        return None
    
    cx = np.mean(points[:, 0])
    points[:, 0] = cx + 0.72 * (points[:, 0] - cx)
    points[:2, 1] = shoulder_y + 0.12 * (hip_y - shoulder_y)
    points[2:, 1] = hip_y - 0.04 * (hip_y - shoulder_y)
    
    h, w = image.shape[:2]
    if np.any(points < 0) or np.any(points[:, 0] >= w) or np.any(points[:, 1] >= h):
        return None
    if cv2.contourArea(points) < 180:
        return None
    
    # 排除其他人头部
    for other in other_poses:
        for x, y, score in np.asarray(other)[:5]:
            if score > 0.5 and cv2.pointPolygonTest(points, (float(x), float(y)), False) >= 0:
                return None
    
    if points[0, 0] > points[1, 0]:
        points = points[[1, 0, 3, 2]]
    
    transform = cv2.getPerspectiveTransform(points, np.float32([[0, 0], [31, 0], [31, 47], [0, 47]]))
    patch = cv2.warpPerspective(image, transform, (32, 48))
    hsv = cv2.cvtColor(patch, cv2.COLOR_BGR2HSV)
    
    hist = cv2.calcHist([hsv], [0, 1], None, [12, 4], [0, 180, 0, 256]).reshape(-1)
    hist = np.sqrt(hist / max(float(hist.sum()), 1))
    
    lab = cv2.cvtColor(patch, cv2.COLOR_BGR2LAB).astype(np.float32) / 255
    lab[:, :, 0] = np.clip(lab[:, :, 0] - np.median(lab[:, :, 0]) + 0.5, 0, 1)
    grid = cv2.resize(lab, (4, 6), interpolation=cv2.INTER_AREA).reshape(-1)
    
    return np.concatenate((hist, grid)).round(5).tolist()


def garment_distance(a, b):
    """计算服装描述符距离"""
    a = np.asarray(a)
    b = np.asarray(b)
    return float(0.65 * np.sqrt(max(0, 1 - np.dot(a[:48], b[:48]))) + 0.35 * np.mean(np.abs(a[48:] - b[48:])))


class GarmentLinker:
    """Tentative clothing links, with group-wide exclusion and bounded sampling."""

    def __init__(self, max_distance=0.12, margin=0.04, max_gap=12, *, audit=False):
        self.max_distance = max_distance
        self.margin = margin
        self.max_gap = max_gap
        self.tracks = {}
        self.groups = {}
        self.conflicts = 0
        self.audit = Counter() if audit else None
        self.sample_counts = Counter() if audit else None
        self.elapsed = 0.0
    
    def _count(self, key):
        if self.audit is not None:
            self.audit[key] += 1
    
    def update(self, people, timestamp, shot):
        started = perf_counter()
        live = {p['id'] for p in people}
        for p in people:
            if p['id'] not in self.tracks:
                group = f"g{len(self.tracks) + 1:04d}"
                self.tracks[p['id']] = dict(
                    group=group, root=group, shot=shot, co_seen=set(),
                    votes=0, candidate=None, first_vote=timestamp,
                    last_sample=-1, linked=False, gallery=deque(maxlen=24)
                )
                self.groups[group] = {p['id']}
            
            track = self.tracks[p['id']]
            track['co_seen'].update(live - {p['id']})
            track['last_seen'] = timestamp
            track['last_shot'] = shot
        # A later co-occurrence disproves the entire tentative group. Reset all
        # its members, retaining co_seen so transitive merging cannot restore it.
        for group, members in list(self.groups.items()):
            if len(members & live) > 1:
                self.conflicts += 1
                self._count('conflicts')
                del self.groups[group]
                for identity in members:
                    track = self.tracks[identity]
                    track.update(group=track['root'], linked=False, candidate=None, votes=0)
                    self.groups[track['root']] = {identity}

        for p in people:
            self._count('observations')
            track = self.tracks[p['id']]
            descriptor = p.get('garment')
            if descriptor is None:
                self._count('missing_descriptor')
                continue
            if track['linked']:
                self._count('linked_gallery_frozen')
                continue
            if timestamp - track['last_sample'] < .2 - 1e-6:
                self._count('sample_throttled')
                continue
            track['gallery'].append(descriptor)
            track['last_sample'] = timestamp
            self._count('gallery_samples')
            if self.sample_counts is not None:
                self.sample_counts[p['id']] += 1
            self._count('match_attempts')
            own_members = self.groups[track['group']]
            candidates = []
            # Rank distinct groups, not multiple fragments from the same group.
            for group, members in self.groups.items():
                if group == track['group']:
                    continue
                if any(self.tracks[a]['co_seen'] & members for a in own_members):
                    continue
                eligible = [self.tracks[m] for m in members
                            if self.tracks[m]['shot'] != shot
                            and timestamp - self.tracks[m]['last_seen'] <= self.max_gap
                            and self.tracks[m]['gallery']]
                if not eligible:
                    continue
                distance = min(garment_distance(descriptor, g) for other in eligible for g in other['gallery'])
                candidates.append((distance, group))
            if not candidates:
                track.update(candidate=None, votes=0)
                self._count('no_candidate')
                continue
            candidates.sort()
            best_dist, best_group = candidates[0]
            if best_dist >= self.max_distance:
                track.update(candidate=None, votes=0)
                self._count('distance_rejected')
                continue
            if len(candidates) > 1 and candidates[1][0] - best_dist < self.margin:
                track.update(candidate=None, votes=0)
                self._count('ambiguous')
                continue
            if self.groups[best_group] & live:
                track.update(candidate=None, votes=0)
                self._count('target_active')
                continue
            if track['candidate'] == best_group:
                track['votes'] += 1
            else:
                track.update(candidate=best_group, votes=1, first_vote=timestamp)
            if track['votes'] < 4 or timestamp - track['first_vote'] < .6 - 1e-6:
                self._count('awaiting_votes')
                continue
            group = min(track['group'], best_group)
            other_group = max(track['group'], best_group)
            members = self.groups.pop(other_group)
            self.groups[group].update(members)
            for identity in self.groups[group]:
                self.tracks[identity].update(group=group, linked=True)
            self._count('merges')
        self.elapsed += perf_counter() - started

    def links(self):
        # Include the root too: otherwise it and its children count separately.
        return {identity: {'group_id': group, 'tentative': True}
                for group, members in self.groups.items() if len(members) > 1
                for identity in members}


def create_garment_linker(audit=False):
    """从全局配置创建GarmentLinker实例"""
    config = get_config()
    return GarmentLinker(
        max_distance=config.appearance.max_distance,
        margin=config.appearance.margin,
        max_gap=config.appearance.max_gap,
        audit=audit
    )

