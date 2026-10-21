"""Audit cached detections with the production pipeline, without identity claims.

Reports observable coverage/fragmentation proxies and garment rejection reasons.
No ground truth means no IDF1, identity-switch rate, or accuracy can be computed.
"""
import argparse
from collections import defaultdict
import hashlib
import json
from pathlib import Path
import statistics
import time

from centerstage.appearance import GarmentLinker
from centerstage.pipeline import AnalysisPipeline, PipelineConfig
from centerstage.scoring import totals


class TimedLinker(GarmentLinker):
    def __init__(self):
        super().__init__(audit=True)
        self.elapsed = 0.0

    def update(self, *args, **kwargs):
        start = time.perf_counter()
        super().update(*args, **kwargs)
        self.elapsed += time.perf_counter() - start


def summarize_frames(frames):
    tracks = defaultdict(lambda: dict(observations=0, observed_seconds=0.0))
    shots = defaultdict(lambda: dict(tracks=set(), maximum_simultaneous=0))
    for frame in frames:
        shot = shots[frame['shot']]
        shot['maximum_simultaneous'] = max(shot['maximum_simultaneous'], len(frame['people']))
        for person in frame['people']:
            row = tracks[person['id']]
            row['observations'] += 1
            # Sum actual observed intervals; don't count gaps as visibility.
            row['observed_seconds'] += max(0, frame['end'] - frame['t'])
            shot['tracks'].add(person['id'])
    counts = [row['observations'] for row in tracks.values()]
    return dict(
        frames=len(frames), tracks=len(tracks), shots=len(shots),
        median_observations=statistics.median(counts) if counts else 0,
        tracks_at_most_3_observations=sum(n <= 3 for n in counts),
        tracks_at_most_10_observations=sum(n <= 10 for n in counts),
        median_observed_seconds=round(statistics.median(row['observed_seconds'] for row in tracks.values()), 6) if tracks else 0,
        unknown_center_seconds=round(totals(frames)[1], 6),
        per_shot=[dict(shot=key, tracks=len(row['tracks']), maximum_simultaneous=row['maximum_simultaneous'])
                  for key, row in sorted(shots.items())],
    )


def audit(rows, duration, config):
    pipeline = AnalysisPipeline(config)
    pipeline.linker = TimedLinker()
    frames = []
    start = time.perf_counter()
    for row in rows:
        frames.extend(pipeline.feed(row['t'], row['shot'], row['width'], row['height'],
            row['boxes'], row['confidence'], row['pose'], garments=row.get('garments')))
    frames.extend(pipeline.finish(duration))
    elapsed = time.perf_counter() - start
    links = pipeline.linker.links()
    sample_counts = pipeline.linker.sample_counts
    report = summarize_frames(frames)
    report.update(
        pipeline=config.metadata(),
        replay_seconds=round(elapsed, 6),
        garment_association_seconds=round(pipeline.linker.elapsed, 6),
        gallery_tracks=len(sample_counts),
        gallery_tracks_at_least_3_samples=sum(n >= 3 for n in sample_counts.values()),
        tentative_groups=len({r['group_id'] for r in links.values()}),
        tentatively_linked_tracks=len(links),
        conflicts=pipeline.linker.conflicts,
        garment_events=dict(sorted(pipeline.linker.audit.items())),
    )
    return report, frames, links


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('cache', type=Path)
    parser.add_argument('output', type=Path)
    parser.add_argument('--duration', type=float, required=True)
    parser.add_argument('--fps', type=float, default=10)
    parser.add_argument('--tracker', choices=['all', 'ocsort', 'bytetrack', 'cbiou'], default='all')
    args = parser.parse_args()
    data = args.cache.read_bytes()
    rows = [json.loads(line) for line in data.splitlines() if line.strip()]
    if not rows or args.duration < rows[-1]['t']:
        parser.error('Cache must be nonempty and duration must cover the last sample')
    # Missing features are not evidence that the video contains no usable garments.
    enriched = all('garments' in row for row in rows)
    detections = sum(len(row['boxes']) for row in rows)
    usable = sum(g is not None for row in rows for g in row.get('garments', []))
    output = dict(schema_version=1, cache_sha256=hashlib.sha256(data).hexdigest(),
        duration=args.duration, detection_observations=detections,
        garment_features_present=enriched,
        usable_garment_observations=usable if enriched else None,
        usable_garment_fraction=usable / detections if enriched and detections else None,
        scope='Cached replay only; excludes decode, detection, descriptor extraction, OCR and browser playback.',
        accuracy=None, identity_switches=None, idf1=None,
        ground_truth='Absent. Track counts, coverage and rejection events are diagnostics, not accuracy.',
        reports=[])
    args.output.mkdir(parents=True, exist_ok=True)
    for name in ('ocsort', 'bytetrack', 'cbiou'):
        if args.tracker not in ('all', name):
            continue
        report, frames, links = audit(rows, args.duration, PipelineConfig(args.fps, name))
        output['reports'].append(report)
        (args.output / f'{name}.jsonl').write_text(''.join(json.dumps(f) + '\n' for f in frames))
        (args.output / f'{name}-links.json').write_text(json.dumps(links, indent=2))
        print(json.dumps({k: v for k, v in report.items() if k != 'per_shot'}), flush=True)
    (args.output / 'audit.json').write_text(json.dumps(output, indent=2) + '\n')


if __name__ == '__main__':
    main()
