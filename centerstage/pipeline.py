"""One timestamp-preserving tracking/center pipeline for live jobs and replay."""
from dataclasses import asdict, dataclass
import math

import numpy as np
import supervision as sv
from trackers import ByteTrackTracker, CBIoUTracker, OCSORTTracker

from .scoring import CenterScorer, CenterWindow, create_scorer
from .appearance import GarmentLinker, garment_descriptor, create_garment_linker


@dataclass(frozen=True)
class PipelineConfig:
    sample_rate: float = 10
    tracker: str = 'ocsort'
    lost_seconds: float = .5
    minimum_hits: int = 2
    garment_matching: bool = True

    def __post_init__(self):
        if not 0 < self.sample_rate <= 60:
            raise ValueError('Invalid sample rate')
        if self.tracker not in ('ocsort', 'bytetrack', 'cbiou'):
            raise ValueError('Unknown tracker')
        if not 0 <= self.lost_seconds <= 5 or not 1 <= self.minimum_hits <= 10:
            raise ValueError('Invalid tracking configuration')

    def metadata(self):
        return dict(asdict(self), version=5, center_rule='visual-center-v5-face-count',appearance_rule='garment-only-v2-conservative',confirmation='one-frame-lookahead')

    def create_tracker(self):
        common = dict(frame_rate=self.sample_rate, minimum_consecutive_frames=self.minimum_hits,
                      lost_track_buffer=round(30*self.lost_seconds), high_conf_det_threshold=.5)
        if self.tracker == 'ocsort':
            return OCSORTTracker(**common, minimum_iou_threshold=.2)
        cls = ByteTrackTracker if self.tracker == 'bytetrack' else CBIoUTracker
        return cls(**common, track_activation_threshold=.55)


class AnalysisPipeline:
    def __init__(self, config):
        self.config = config
        self.shot = None
        self.pending = None
        self.window = CenterWindow()
        self.closed = False
        self.linker = create_garment_linker()

    def feed(self, timestamp, shot, width, height, boxes, confidence, poses, image=None, garments=None):
        if self.closed:
            raise ValueError('Pipeline already finished')
        if not math.isfinite(timestamp) or timestamp < 0 or min(width, height) <= 0:
            raise ValueError('Invalid sample timestamp or dimensions')
        if self.pending is not None and timestamp <= self.pending['t']:
            raise ValueError('Sample timestamps must increase')
        if self.shot != shot:
            self.shot = shot
            self.tracker = self.config.create_tracker()
            self.scorer = create_scorer()
        boxes = np.asarray(boxes, dtype=np.float32).reshape(-1, 4)
        poses=np.asarray(poses,dtype=np.float32).reshape(-1,17,3)
        confidence = np.asarray(confidence, dtype=np.float32)
        if (len(boxes) != len(poses) or confidence.shape != (len(boxes),)
                or not all(np.isfinite(x).all() for x in (boxes, poses, confidence))):
            raise ValueError('Invalid detection output')
        if garments is None:
            garments=[garment_descriptor(image,p,poses) if image is not None and self.config.garment_matching else None for p in poses]
        garment_valid=np.asarray([g is not None for g in garments])
        garment_data=np.asarray([g if g is not None else [0.]*120 for g in garments],dtype=np.float32).reshape(-1,120)
        detection = sv.Detections(xyxy=boxes, confidence=np.asarray(confidence, dtype=np.float32),
            class_id=np.zeros(len(boxes), int),
            data={'pose': poses,'garment':garment_data,'garment_valid':garment_valid})
        tracked = self.tracker.update(detection, timestamp=timestamp)
        people = []
        has_confirmed=any(int(key)>=0 for key in tracked.tracker_id) if tracked.tracker_id is not None else False
        for n, box in enumerate(tracked.xyxy):
            identity = int(tracked.tracker_id[n])
            provisional=identity<0
            pose_conf=tracked.data['pose'][n][:,2]
            if provisional and (has_confirmed or tracked.confidence[n]<.8 or np.min(pose_conf[[5,6]])<.8 or np.max(pose_conf[[11,12]])<.65):
                continue
            pose = tracked.data['pose'][n].copy()
            pose[:, 0] /= width
            pose[:, 1] /= height
            pose[:, :2] = np.clip(pose[:, :2], 0, 1)
            people.append(dict(id=f'?{shot}-{timestamp}-{n}' if provisional else f'{shot+1}-{identity}',
                box=np.round(np.clip(box/np.array([width, height, width, height]), 0, 1), 5).tolist(),
                confidence=round(float(tracked.confidence[n]), 4), pose=np.round(pose, 4).tolist(),
                garment=tracked.data['garment'][n].tolist() if tracked.data['garment_valid'][n] else None,
                _provisional=provisional))
        if self.config.garment_matching:self.linker.update([p for p in people if not p['_provisional']],timestamp,shot)
        for person in people:person.pop('garment',None)
        self._confirm_previous(people,shot,timestamp)
        scorer=self.scorer
        if people and all(p['_provisional'] for p in people):
            self.scorer.update([],timestamp)
            scorer=create_scorer()  # Provisional evidence must not alter confirmed scoring history.
        centers, state = scorer.update(people, timestamp)
        settled = []
        if self.pending is not None:
            self.pending['end'] = round(timestamp, 6)
            settled = self.window.feed(self.pending)
        self.pending = dict(t=round(timestamp, 6), end=round(timestamp, 6), shot=shot,
                            people=people, centers=centers, state=state,reason=scorer.reason)
        return settled

    def _confirm_previous(self, people, shot, timestamp):
        if self.pending is None:return
        def overlap(a,b):
            x1=max(a[0],b[0]);y1=max(a[1],b[1]);x2=min(a[2],b[2]);y2=min(a[3],b[3])
            intersection=max(0,x2-x1)*max(0,y2-y1)
            union=(a[2]-a[0])*(a[3]-a[1])+(b[2]-b[0])*(b[3]-b[1])-intersection
            return intersection/max(union,1e-9)
        confirmed=[p for p in people if not p.get('_provisional')]
        existing={p['id'] for p in self.pending['people'] if not p.get('_provisional')}
        candidates={}
        if self.pending['shot']==shot and timestamp-self.pending['t']<=.2+1e-5:
            for p in self.pending['people']:
                if not p.get('_provisional'):continue
                scores=sorted([(overlap(p['box'],c['box']),c['id']) for c in confirmed],reverse=True)
                if scores and scores[0][0]>=.6 and (len(scores)==1 or scores[0][0]-scores[1][0]>=.15) and scores[0][1] not in existing:
                    candidates[p['id']]=scores[0][1]
        mapping={old:new for old,new in candidates.items() if list(candidates.values()).count(new)==1}
        settled=[]
        for p in self.pending['people']:
            if p.pop('_provisional',False):
                old=p['id']
                if old not in mapping:continue
                p['id']=mapping[old]
            settled.append(p)
        self.pending['people']=settled
        live={p['id'] for p in settled}
        self.pending['centers']=[mapping.get(k,k) for k in self.pending['centers'] if mapping.get(k,k) in live]

    def finish(self, duration=None):
        """Cancellation omits the unbounded last sample; never fills to EOF."""
        if self.closed:
            return []
        self.closed = True
        self._confirm_previous([],None,float('inf'))
        settled = []
        if duration is not None and self.pending is not None and duration > self.pending['t']:
            if not math.isfinite(duration): raise ValueError('Invalid video duration')
            self.pending['end'] = duration
            settled.extend(self.window.feed(self.pending))
        settled.extend(self.window.finish())
        return settled


