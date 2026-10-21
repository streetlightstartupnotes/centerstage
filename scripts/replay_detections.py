"""Replay a cached video through each tracker without rerunning the detector."""
import argparse,json,time
from pathlib import Path
from centerstage.pipeline import AnalysisPipeline,PipelineConfig
from centerstage.scoring import totals
p=argparse.ArgumentParser();p.add_argument('cache',type=Path);p.add_argument('output',type=Path);p.add_argument('--fps',type=float,default=10);p.add_argument('--duration',type=float,required=True);p.add_argument('--lost-seconds',type=float,default=.5);p.add_argument('--min-hits',type=int,default=2);p.add_argument('--tracker',choices=['all','ocsort','bytetrack','cbiou'],default='all');a=p.parse_args()
if not (0<=a.lost_seconds<=5 and 1<=a.min_hits<=10):p.error('lost-seconds must be 0..5; min-hits must be 1..10')
raw=[json.loads(s) for s in a.cache.read_text().splitlines()];a.output.mkdir(exist_ok=True,parents=True)
for name in ('ocsort','bytetrack','cbiou'):
 if a.tracker not in ('all',name):continue
 config=PipelineConfig(a.fps,name,a.lost_seconds,a.min_hits)
 pipeline=AnalysisPipeline(config);frames=[];start=time.perf_counter()
 for r in raw:
  frames.extend(pipeline.feed(r['t'],r['shot'],r['width'],r['height'],r['boxes'],r['confidence'],r['pose'],garments=r.get('garments')))
 frames.extend(pipeline.finish(a.duration))
 (a.output/f'{name}.jsonl').write_text(''.join(json.dumps(f)+'\n' for f in frames))
 (a.output/f'{name}-links.json').write_text(json.dumps(pipeline.linker.links(),indent=2))
 print(json.dumps(dict(tracker=name,pipeline=config.metadata(),unknown=totals(frames)[1],tracks=len({p['id'] for f in frames for p in f['people']}),shots=len({f['shot'] for f in frames}),elapsed=time.perf_counter()-start)),flush=True)
