#!/usr/bin/env python3
"""Measure the running local service; no model copy or invented accuracy score."""
import argparse
import json
import math
import time
from pathlib import Path

import httpx


def summarize(payload):
    job=payload['job'];frames=payload['frames'];covered=unknown=equivalent=0.0;last=0.0
    for frame in frames:
        start,end=frame['t'],frame['end']
        if not (math.isfinite(start) and math.isfinite(end) and start>=last-1e-6 and end>start):
            raise ValueError('Invalid or overlapping media intervals')
        centers=set(frame['centers']);visible={p['id'] for p in frame['people']}
        if not centers<=visible:raise ValueError('Center references an absent track')
        covered+=end-start
        if not centers:unknown+=end-start
        else:equivalent+=end-start
        last=end
    return dict(job_id=job['id'],status=job['status'],video=job['video'],
        sample_rate=job['analysis_fps'],frames=len(frames),track_fragments=job['track_count'],
        elapsed_seconds=job['elapsed'],realtime_factor=job['speed'],
        first_result_seconds=job['first_result_seconds'],ready_seconds=job['ready_seconds'],
        confirmed_until=last,covered_seconds=covered,unknown_center_seconds=unknown,
        center_equivalent_seconds=equivalent,supported_name_count=job['name_status']['supported_name_count'],
        accounting_error=abs(covered-unknown-equivalent),
        accuracy=None,accuracy_note='No independent per-frame C-position or identity ground truth supplied.')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('video',nargs='?',type=Path)
    parser.add_argument('--job',help='Audit an existing job instead of importing a video')
    parser.add_argument('--url',default='http://127.0.0.1:8640')
    parser.add_argument('--output',type=Path,default=Path('evidence/benchmark.json'))
    args=parser.parse_args()
    if bool(args.video)==bool(args.job):parser.error('Provide a video path or --job, not both')
    with httpx.Client(base_url=args.url,timeout=600) as client:
        if args.video:
            with args.video.open('rb') as source:
                response=client.post('/api/jobs',files={'file':(args.video.name,source,'video/mp4')},data={'analysis_fps':10})
            response.raise_for_status();identity=response.json()['id']
        else:identity=args.job
        deadline=time.monotonic()+3600
        while True:
            response=client.get('/api/jobs/'+identity);response.raise_for_status();job=response.json()
            if job['status'] in ('complete','failed','cancelled','interrupted'):break
            if time.monotonic()>deadline:raise TimeoutError('Analysis still running; results remain in the service')
            time.sleep(1)
        response=client.get('/api/jobs/'+identity+'/export');response.raise_for_status()
        report=summarize(response.json())
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(report,ensure_ascii=False))
    return 0 if report['status']=='complete' and report['accounting_error']<1e-5 else 1


if __name__=='__main__':
    raise SystemExit(main())
