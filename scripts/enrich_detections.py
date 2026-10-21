"""Add non-biometric clothing descriptors to an existing detection cache."""
import argparse,json
from centerstage.video import samples
from centerstage.engine import inspect_video
from centerstage.appearance import garment_descriptor

p=argparse.ArgumentParser()
p.add_argument('video');p.add_argument('cache');p.add_argument('output');p.add_argument('--fps',type=float,default=10)
a=p.parse_args();info=inspect_video(a.video)
with open(a.cache) as source,open(a.output,'w') as out:
    rows=iter(source)
    count=0
    for sample in samples(a.video,a.fps,info['fps']):
        row=json.loads(next(rows))
        if abs(row['t']-sample.t)>1e-5 or sample.image.shape[:2]!=(row['height'],row['width']):
            raise ValueError('Cache/video timestamps or dimensions differ')
        row['garments']=[garment_descriptor(sample.image,pose,row['pose']) for pose in row['pose']]
        out.write(json.dumps(row)+'\n');count+=1
    if next(rows,None) is not None:raise ValueError('Extra cache frames')
print(json.dumps(dict(frames=count,output=a.output)))
