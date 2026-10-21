"""Rank supported names and anonymous tracks without conflating them with people."""
from .annotations import label_at


def center_statistics(frames, labels, annotations=(), until=None, appearance_links=None):
    appearance_links=appearance_links or {}
    rows, tracks, by_track = {}, {}, {}
    for a in annotations:
        if a.get('evidence') != 'explicit_person_annotation': continue
        by_track.setdefault(a['track_id'], []).append(a)
    unknown = unnamed = covered = 0.0
    confirmed = frames[-1]['end'] if frames else 0
    until = confirmed if until is None else max(0, min(until, confirmed))
    for f in frames:
        # Diagnostic fragment IDs are not member identities or a member count.
        for p in f.get('people', []):
            tracks.setdefault(p['id'], f'轨迹片段 {len(tracks)+1:03d}')
        for identity in f['centers']:
            tracks.setdefault(identity, f'轨迹片段 {len(tracks)+1:03d}')
        end = min(f['end'], until)
        if end <= f['t']: continue
        covered += end - f['t']
        edges = sorted({f['t'], end, *[t for identity in f['centers'] for a in by_track.get(identity, [])
                                    for t in (a['start'], a['end']) if f['t'] < t < end]})
        for start, stop in zip(edges, edges[1:]):
            entries = {}
            for identity in f['centers']:
                label = label_at(identity, (start+stop)/2, labels, by_track.get(identity, []))
                name = label['name'].strip() if label else tracks[identity]
                key = 'name:'+name.lower() if label else 'track:'+identity
                association=appearance_links.get(identity) if not label else None
                # Co-occurring centers cannot collapse into one because their
                # clothing happens to have the same tentative group ID.
                if association and sum(appearance_links.get(other, {}).get('group_id') == association['group_id']
                                       for other in set(f['centers'])) > 1:
                    association = None
                if association:
                    key='garment:'+association['group_id']
                    name='外观组 '+association['group_id'][1:].lstrip('0').zfill(3)
                entry = entries.setdefault(key, {'name': name, 'named': bool(label), 'tracks': set()})
                if association:entry['association']='garment_similarity'
                entry['tracks'].add(identity)
            dt = stop-start
            if not entries: unknown += dt
            if any(not r['named'] for r in entries.values()): unnamed += dt
            for key, entry in entries.items():
                row = rows.setdefault(key, dict(key=key, name=entry['name'], named=entry['named'],
                    seconds=0., equivalent_seconds=0., tracks=set(), first=start))
                row['seconds'] += dt
                row['equivalent_seconds'] += dt/len(entries)
                row['tracks'].update(entry['tracks'])
                if entry.get('association'):row['association']=entry['association']
    for row in rows.values(): row['track_count'] = len(row.pop('tracks'))
    return {'until': until, 'rows': sorted(rows.values(), key=lambda r: (-r['seconds'], r['first'], r['key'])),
            'unknown': unknown, 'unbound': unnamed, 'covered': covered}


def member_statistics(statistics):
    """Keep unmatched intervals in the summary, never rank fragments as members."""
    return dict(statistics, rows=[row for row in statistics['rows'] if row['named']])
