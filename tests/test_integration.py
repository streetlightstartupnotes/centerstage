"""Contracts spanning decode, pipeline, Agent revisions, persistence and export."""
import io
import json

import pytest
from fastapi.testclient import TestClient

from centerstage.app import create_app
from centerstage.engine import Job, Manager, inspect_video
from centerstage.pipeline import AnalysisPipeline, PipelineConfig
from centerstage.annotations import AnnotationResult, apply_annotations, agent_requests, review_scope
from centerstage.video import samples, scene_samples
from test_engine import FakeModel, make_video


@pytest.mark.parametrize('tracker',['ocsort','bytetrack','cbiou'])
def test_live_decode_and_cached_replay_produce_identical_frames(tmp_path,tracker):
    manager=Manager(tmp_path)
    directory=manager.allocate();path=directory/'video.mp4';make_video(path)
    job=manager.create(path,'generic.mp4',inspect_video(path),tracker=tracker)
    manager.model=FakeModel();manager._analyze(job)
    pipeline=AnalysisPipeline(PipelineConfig(10,tracker));replay=[];shot=0
    for sample in scene_samples(samples(path,10,12),10):
        if sample.cut:shot+=1
        # JSON roundtrip reproduces the actual detection-cache boundary.
        raw=json.loads(json.dumps([x.tolist() for x in manager.model.predict(sample.image)]))
        h,w=sample.image.shape[:2]
        replay.extend(pipeline.feed(sample.t,shot,w,h,*raw))
    replay.extend(pipeline.finish(2))
    assert replay==job.frames
    assert job.meta['pipeline']==pipeline.config.metadata()
    assert pipeline.finish(2)==[]


def streaming_job(tmp_path):
    return Job(tmp_path,dict(id='sample',filename='generic.mp4',video={'duration':100},
        status='analyzing',track_ids=[],annotation_status='pending',annotations=[],roster=[]))


def append(job,start,end):
    job.append(dict(t=start,end=end,shot=0,centers=['1-1'],people=[dict(id='1-1',box=[.3,.1,.7,.9])]),io.StringIO())


def test_agent_follows_new_evidence_without_spinning_on_unresolved(tmp_path):
    job=streaming_job(tmp_path)
    assert not agent_requests([job])
    append(job,0,1)
    assert not agent_requests([job])
    append(job,1,3)
    assert len(agent_requests([job]))==1
    old=review_scope(job)
    append(job,3,34)  # Analysis advances while the external adapter is running.
    apply_annotations(job,AnnotationResult(status='unresolved',reviewed=old))
    assert len(agent_requests([job]))==1  # Only the old 3 seconds were reviewed.
    apply_annotations(job,AnnotationResult(status='unresolved'))
    assert not agent_requests([job])
    job.meta['status']='complete'
    assert len(agent_requests([job]))==1  # Final partial chunk still gets a review.
    apply_annotations(job,AnnotationResult(status='partial'))
    assert not agent_requests([job])
    job.meta['roster_revision']=1
    assert len(agent_requests([job]))==1
    apply_annotations(job,AnnotationResult(status='unresolved'))
    assert not agent_requests([job])
    job.meta['caption_text']=[{'t':.1,'rows':[]}]
    assert len(agent_requests([job]))==1


def test_agent_merge_conflict_late_roster_and_all_consumers(tmp_path):
    manager=Manager(tmp_path/'data');directory=manager.allocate();path=directory/'video.mp4';make_video(path)
    job=manager.create(path,'generic.mp4',inspect_video(path));manager.model=FakeModel();manager._analyze(job)
    identity=job.meta['id'];base=f'/api/jobs/{identity}'
    job.meta['caption_text']=[{'t':.5,'rows':[{'text':'[Example]','confidence':.99}]}]
    with TestClient(create_app(manager,start_worker=False)) as client:
        assert client.get('/app.js').headers['cache-control']=='no-cache'
        context=client.get(base+'/agent-context').json()
        track=context['tracks'][0]['track_id']
        item=dict(track_id=track,name='Example',start=.5,end=1,evidence='explicit_person_annotation',
            source_url='https://example.org/labelled-performance',source_note='Synthetic test: source explicitly labels the performer.')
        result=dict(status='partial',mode='merge',base_revision=0,reviewed=context['review'],annotations=[item])
        future=dict(result,reviewed=dict(context['review'],frame_count=0))
        assert client.put(base+'/annotations',json=future).status_code==422
        assert client.put(base+'/annotations',json=result).status_code==200
        assert client.put(base+'/annotations',json=result).status_code==409
        assert client.put(base+'/annotations',json=dict(status='unresolved',mode='merge',base_revision=1)).status_code==200
        assert client.get(base+'/frames').json()['job']['annotations']==[item]
        stats=client.get(base+'/statistics').json()
        named=next(row for row in stats['rows'] if row['named'])
        assert named['name']=='Example' and named['seconds']==pytest.approx(.5)
        assert client.get(base+'/export').json()['statistics']==stats
        assert 'Example,0.5' in client.get(base+'/export?format=csv').text
        assert not job.meta.get('captions')
        roster={'members':[{'name':'Example','source':'https://example.org/credits'}]}
        assert client.put(base+'/roster',json=roster).status_code==200
        assert job.meta['captions'][0]['names']==['Example']  # No second OCR inference.
        assert job.meta['roster_revision']==1
        assert any(t['type']=='person_annotations' for t in client.get('/api/agent/requests').json()['requests'])
        assert client.put(base+'/roster',json=roster).status_code==200
        assert job.meta['roster_revision']==1  # Idempotent source submission.
        assert job.meta['annotations']==[item] and job.meta['labels']=={}
        restored=Manager(manager.data).jobs[identity]
        assert restored.tracks==job.tracks
        assert restored.meta['annotation_revision']==2
        assert restored.meta['annotations']==[item]


def test_adapter_binds_result_to_snapshot_and_preserves_previous_annotations(monkeypatch):
    from types import SimpleNamespace
    from centerstage.agent_worker import work
    calls=[]
    context={'job':{'annotation_revision':4},'review':dict(frame_count=40,roster_revision=2,caption_count=0,terminal=False)}
    class Response:
        def __init__(self,value):self.value=value
        def json(self):return self.value
        def raise_for_status(self):pass
    class Client:
        def __init__(self,**kw):pass
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def get(self,path):
            return Response({'requests':[dict(job_id='x',type='person_annotations')]} if path.endswith('/requests') else context)
        def put(self,path,json):calls.append(json);return Response({})
    monkeypatch.setattr('centerstage.agent_worker.httpx.Client',Client)
    monkeypatch.setattr('centerstage.agent_worker.subprocess.run',lambda *a,**k:SimpleNamespace(returncode=0,stdout='{"status":"unresolved","annotations":[]}'))
    work('http://127.0.0.1',['adapter'],once=True)
    assert calls[0]['base_revision']==4 and calls[0]['mode']=='merge'
    assert calls[0]['reviewed']==context['review']


@pytest.mark.parametrize('case',['stable','cut','jump','unconfirmed'])
def test_unconfirmed_first_sample_is_only_backfilled_by_unambiguous_next_frame(monkeypatch,case):
    import numpy as np
    class Tracker:
        def __init__(self):self.n=0
        def update(self,detection,timestamp):
            detection.tracker_id=np.array([-1 if self.n==0 or case=='unconfirmed' else 7])
            self.n+=1
            return detection
    tracker=Tracker();monkeypatch.setattr(PipelineConfig,'create_tracker',lambda _:tracker)
    pipeline=AnalysisPipeline(PipelineConfig(10));out=[]
    pose=np.zeros((1,17,3),np.float32);pose[:,:,0]=50;pose[:,:,1]=50;pose[:,:,2]=.99
    # One occluded hip must not erase a clear subject with both shoulders and the other hip.
    pose[0,12,2]=.4
    for i in range(4):
        box=np.array([[20,10,80,95]],np.float32)
        if case=='jump' and i:box[:,[0,2]]+=60
        out.extend(pipeline.feed(i/10,int(case=='cut' and i>0),160,100,box,[.95],pose))
    out.extend(pipeline.finish(.4))
    assert not any(p.get('_provisional') or p['id'].startswith('?') for f in out for p in f['people'])
    if case=='stable':assert out[0]['centers']==['1-7']
    else:assert out[0]['centers']==[] and out[0]['people']==[]
