"""Cache detections once for reproducible tracker/scorer comparisons on any video."""
import argparse,json,time
from pathlib import Path
from centerstage.model import load_model
from centerstage.video import samples,scene_samples
from centerstage.engine import inspect_video
p=argparse.ArgumentParser();p.add_argument('video',type=Path);p.add_argument('output',type=Path);p.add_argument('--fps',type=int,default=10);a=p.parse_args()
model=load_model(Path('.centerstage/models/rtmo-s.onnx'));info=inspect_video(a.video);start=time.perf_counter();shot=0
with a.output.open('w') as out:
 for i,s in enumerate(scene_samples(samples(a.video,a.fps,info['fps']),a.fps)):
  if s.cut:shot+=1
  boxes,confidence,pose=model.predict(s.image);h,w=s.image.shape[:2]
  out.write(json.dumps(dict(t=s.t,shot=shot,boxes=boxes.tolist(),confidence=confidence.tolist(),pose=pose.tolist(),width=w,height=h))+'\n')
  if i%300==0:print(i,round(s.t,1),round(time.perf_counter()-start,1),flush=True)
print('elapsed',time.perf_counter()-start,'shots',shot+1,flush=True)
