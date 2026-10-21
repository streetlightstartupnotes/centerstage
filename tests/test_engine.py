import io
import json
import shutil
from pathlib import Path

import av
import numpy as np
import pytest
from fastapi.testclient import TestClient

from centerstage.app import create_app
from centerstage.engine import Manager, inspect_video
from centerstage.scoring import CenterScorer, totals, named_totals
from centerstage.captions import append_caption, read_names
from centerstage.rosters import candidate_roster


def make_video(path, count=24):
    with av.open(str(path),"w") as out:
        stream=out.add_stream("mpeg4",rate=12)
        stream.width=320;stream.height=240;stream.pix_fmt="yuv420p"
        for i in range(count):
            image=np.full((240,320,3),50+i,np.uint8)
            frame=av.VideoFrame.from_ndarray(image,format="rgb24")
            for packet in stream.encode(frame):out.mux(packet)
        for packet in stream.encode():out.mux(packet)


class FakeModel:
    def predict(self,image):
        poses=np.zeros((1,17,3),np.float32);poses[:,:,0]=160;poses[:,:,1]=120;poses[:,:,2]=.99
        return np.array([[90,20,230,230]],np.float32),np.array([.99],np.float32),poses


@pytest.mark.parametrize("tracker", ["ocsort", "bytetrack", "cbiou"])
def test_real_decode_intervals_and_restart(tmp_path, tracker):
    manager=Manager(tmp_path)
    directory=manager.allocate();path=directory/"video.mp4";make_video(path)
    job=manager.create(path,"sample.mp4",inspect_video(path),tracker=tracker)
    manager.model=FakeModel();manager._analyze(job);job.save()
    assert job.meta["status"]=="complete"
    assert len(job.frames)==20  # 12 fps source sampled at 10 fps, no rounded-time drift.
    assert abs(job.frames[0]["t"])<.001
    assert abs(job.frames[-1]["end"]-2)<.01
    assert all(abs(a["end"]-b["t"])<1e-5 for a,b in zip(job.frames,job.frames[1:]))
    assert any(f["centers"] for f in job.frames)
    restored=Manager(tmp_path).jobs[job.meta["id"]]
    assert restored.frames==job.frames
    assert restored.meta["status"]=="complete"


def test_dual_totals_are_media_time_and_replay_independent():
    frames=[{"t":0,"end":2,"centers":["a","b"]},{"t":2,"end":3,"centers":[]}]
    ranking,unknown=totals(frames)
    assert [r["seconds"] for r in ranking]==[2,2]
    assert [r["equivalent_seconds"] for r in ranking]==[1,1]
    assert unknown==1
    assert totals(frames)==totals(frames)
    assert totals(frames,until=1)[0][0]["seconds"]==1


def test_api_upload_ranges_labels_exports_and_origin(tmp_path):
    manager=Manager(tmp_path/"data")
    path=tmp_path/"sample.mp4";make_video(path)
    with TestClient(create_app(manager,start_worker=False)) as client:
        response=client.post('/api/jobs',files={"file":("sample.mp4",path.read_bytes(),"video/mp4")})
        assert response.status_code==201
        identity=response.json()["id"];job=manager.jobs[identity]
        manager.model=FakeModel();manager._analyze(job);job.save()
        assert client.get(f'/api/jobs/{identity}/video',headers={"Range":"bytes=0-15"}).status_code==206
        batch=client.get(f'/api/jobs/{identity}/frames').json()
        assert batch["next"]==len(job.frames)
        assert batch["job"]["track_count"]==len(job.meta["track_ids"])
        assert "people_count" not in batch["job"]
        assert not client.get(f'/api/jobs/{identity}/frames?after={batch["next"]}').json()["frames"]
        track=next(p["id"] for f in job.frames for p in f["people"])
        assert client.put(f'/api/jobs/{identity}/labels/{track}',json={"name":"测试成员"}).status_code==200
        exported=client.get(f'/api/jobs/{identity}/export').json()
        assert exported["job"]["labels"][track]["name"]=="测试成员"
        assert "测试成员" in client.get(f'/api/jobs/{identity}/export?format=csv').text
        assert client.put(f'/api/jobs/{identity}/labels/{track}',json={"name":"=HYPERLINK(1)"}).status_code==200
        assert "'=HYPERLINK" in client.get(f'/api/jobs/{identity}/export?format=csv').text
        assert client.post('/api/jobs',files={"file":("bad.mp4",b'not a video')}).status_code==422
        assert client.get('/api/jobs',headers={"Origin":"https://evil.invalid"}).status_code==403
        assert client.get('/api/jobs',headers={"Host":"evil.invalid"}).status_code==400
        assert client.get(f'/api/jobs/{identity}/frames?after=-1').status_code==422
        renamed=client.put(f'/api/jobs/{identity}/title',json={"title":"  NEON 初舞台  "})
        assert renamed.status_code==200 and renamed.json()["title"]=="NEON 初舞台"
        assert renamed.json()["filename"]=="sample.mp4"
        assert client.get('/api/jobs').json()["jobs"][0]["title"]=="NEON 初舞台"
        assert client.put(f'/api/jobs/{identity}/title',json={"title":"   "}).status_code==422


def test_delete_removes_the_library_video(tmp_path):
    manager=Manager(tmp_path/"data")
    path=tmp_path/"sample.mp4";make_video(path)
    with TestClient(create_app(manager,start_worker=False)) as client:
        identity=client.post('/api/jobs',files={"file":("sample.mp4",path.read_bytes(),"video/mp4")}).json()["id"]
        directory=manager.data/"jobs"/identity
        assert directory.is_dir()
        assert client.delete(f'/api/jobs/{identity}').status_code==204
        assert identity not in manager.jobs and not directory.exists()
        assert client.get(f'/api/jobs/{identity}').status_code==404
        assert client.get('/api/jobs').json()["jobs"]==[]
        assert client.delete(f'/api/jobs/{identity}').status_code==404
    assert identity not in Manager(tmp_path/"data").jobs


def test_cancellation_and_interrupted_recovery(tmp_path):
    manager=Manager(tmp_path)
    directory=manager.allocate();path=directory/'video.mp4';make_video(path)
    job=manager.create(path,'sample.mp4',inspect_video(path))
    job.cancel.set();manager.model=FakeModel();manager._analyze(job);job.save()
    assert job.meta['status']=='cancelled'
    assert not job.frames
    job.meta['status']='analyzing';job.save()
    assert Manager(tmp_path).jobs[job.meta['id']].meta['status']=='interrupted'


def test_source_roster_requires_evidence_and_never_sets_labels(tmp_path):
    manager=Manager(tmp_path/'data');path=tmp_path/'sample.mp4';make_video(path)
    with TestClient(create_app(manager,start_worker=False)) as client:
        data=client.post('/api/jobs',files={'file':('sample.mp4',path.read_bytes())},data={'source_url':'https://example.com/show'}).json()
        identity=data['id']
        assert client.get('/api/agent/requests').json()['requests'][0]['job_id']==identity
        url=f'/api/jobs/{identity}/roster'
        assert client.put(url,json={'members':[{'name':'A','source':'javascript:alert(1)'}]}).status_code==422
        assert client.put(url,json={'members':[{'name':'A','source':'https://example.com/show'}]}).status_code==200
        assert client.get('/api/agent/requests').json()['requests']==[]  # No empty-track annotation task.
        assert not client.get(f'/api/jobs/{identity}').json()['labels']


def test_center_loss_does_not_assign_stale_identity():
    scorer=CenterScorer()
    def person():return {'id':'a','box':[.3,.1,.7,.95],'confidence':.99,'pose':[[.5,.5,.99]]*17}
    scorer.update([person()],0)
    assert scorer.update([person()],.4)[0]==['a']
    assert scorer.update([],.5)==([], 'unknown')


def test_ambiguous_uniform_line_does_not_invent_single_center():
    scorer=CenterScorer()
    def people():return [{'id':str(i),'box':[x-.06,.2,x+.06,.9],'confidence':.99,'pose':[[x,.5,.99]]*17} for i,x in enumerate([.2,.4,.6,.8])]
    scorer.update(people(),0)
    assert scorer.update(people(),.4)[0]==[]


def test_phone_display_rotation_is_applied_before_inference(tmp_path):
    # Synthetic fixture: 320x240 black frame, red upper-left square, 90° CCW
    # display matrix. Browser orientation is portrait with red at lower-left.
    manager=Manager(tmp_path)
    directory=manager.allocate();path=directory/'video.mp4'
    shutil.copyfile(Path(__file__).parent/'data/rotation90.mp4',path)
    class OrientationModel:
        def predict(self,image):
            assert image.shape==(320,240,3)
            assert image[290,30,2]>220
            assert image[30,30,2]<20
            return np.empty((0,4),np.float32),np.empty(0,np.float32),np.empty((0,17,3),np.float32)
    manager.model=OrientationModel()
    job=manager.create(path,'rotated.mp4',inspect_video(path))
    manager._analyze(job)
    assert job.meta['status']=='complete'


def test_named_totals_merge_confirmed_tracks_without_double_counting():
    frames=[{'t':0,'end':2,'centers':['a','b']},{'t':2,'end':3,'centers':['c']},{'t':3,'end':4,'centers':['unknown']}]
    labels={k:{'name':'OA','evidence':'user_confirmed'} for k in ('a','b','c')}
    rows,unknown=named_totals(frames,labels)
    assert rows==[{'name':'OA','seconds':3,'equivalent_seconds':3,'track_count':3}]
    assert unknown=={'seconds':1,'equivalent_seconds':1}


def test_caption_names_do_not_turn_lyrics_or_rosters_into_identity():
    names=['OA','YOUNG','VORA','MERCI','HIMEKI']
    assert read_names([{'text':'[OA]','confidence':.99}],names)==['OA']
    assert read_names([{'text':'[VORA, All]','confidence':.99}],names)==[]
    assert read_names([{'text':'[MERCI, OA]','confidence':.99}],names)==['MERCI','OA']
    assert read_names([{'text':'We are young','confidence':.99}],names)==[]
    assert read_names([{'text':'[OA]','confidence':.2}],names)==[]
    assert read_names([{'text':'[WOUNG]','confidence':.99}],names)==['YOUNG']
    assert read_names([{'text':'[MERC]','confidence':.99}],names)==['MERCI']
    assert read_names([{'text':'[HMEKI]','confidence':.99}],names)==['HIMEKI']
    assert read_names([{'text':'[AI]','confidence':.99}],names)==[]
    group,roster=candidate_roster('A2O LITE NEON.mp4')
    assert group=='A2O LITE' and len(roster)==9
    assert candidate_roster('A2O LITE NEON.mp4','none')==('',[])
    meta={'video':{'duration':80},'roster':[{'name':name} for name in names]}
    append_caption(meta,37,[{'text':'[OA]','confidence':.99}])
    append_caption(meta,37.4,[{'text':'[MERCI]','confidence':.99}])
    assert meta['captions'][0]=={'t':37,'end':37.4,'names':['OA'],'evidence':'printed_subtitle','text':['[OA]']}
    assert meta['captions'][1]['names']==['MERCI'] and meta['captions'][1]['t']==37.4
    append_caption(meta,37.6,[{'text':'[VORA, All]','confidence':.99}])
    assert meta['captions'][1]['end']==37.6 and len(meta['captions'])==2


def test_agent_annotations_are_time_scoped_and_reject_conflicts(tmp_path):
    from centerstage.annotations import AnnotationResult,apply_annotations,label_at
    manager=Manager(tmp_path);directory=manager.allocate();path=directory/'video.mp4';make_video(path)
    job=manager.create(path,'another-group.mp4',inspect_video(path));manager.model=FakeModel();manager._analyze(job)
    track=next(p['id'] for f in job.frames for p in f['people'])
    entry=dict(track_id=track,name='Example',start=.5,end=1.0,evidence='explicit_person_annotation',source_url='https://example.org/credited-performance',source_note='Original source has a name tag pointing to this performer in this interval.')
    payload=AnnotationResult(status='partial',annotations=[entry]);apply_annotations(job,payload)
    assert label_at(track,.4,{},job.meta['annotations']) is None
    assert label_at(track,.7,{},job.meta['annotations'])['name']=='Example'
    assert label_at(track,1.0,{},job.meta['annotations']) is None
    with pytest.raises(ValueError):apply_annotations(job,AnnotationResult(status='complete',annotations=[entry,dict(entry,name='Other')]))
    with pytest.raises(ValueError):AnnotationResult(status='complete',annotations=[dict(entry,evidence='singer_subtitle')])
    frames=[dict(t=0,end=2,centers=[track])]
    assert named_totals(frames,{},annotations=[entry])[0][0]['seconds']==.5
    assert named_totals(frames,{},until=.4,annotations=[entry])[0]==[]
    assert named_totals([dict(t=2,end=3,centers=[track])],{track:dict(name='A',evidence='user_confirmed')},until=1)[0]==[]


def test_center_lookahead_aligns_change_and_rejects_transient_candidate():
    from centerstage.scoring import CenterWindow
    frames=[dict(t=i/10,end=(i+1)/10,shot=0,centers=['wrong' if i==3 else 'a']) for i in range(10)]
    window=CenterWindow();output=[]
    for f in frames:output+=window.feed(f)
    output+=window.finish()
    assert [f['t'] for f in output]==[f['t'] for f in frames]
    assert output[0]['centers']==['a']
    assert output[3]['centers']==[]
    assert output[4]['centers']==['a']


def test_scene_detector_keeps_timestamp_and_ignores_exposure_flash():
    from centerstage.video import Sample,scene_samples
    rng=np.random.default_rng(2);base=rng.integers(20,120,(90,160,3),dtype=np.uint8)
    images=[base.copy() for _ in range(20)];images[8]=base+70
    output=list(scene_samples((Sample(i/10,im) for i,im in enumerate(images)),10))
    assert len(output)==20 and not any(s.cut for s in output)
    changed=np.fliplr(base).copy()
    images=[base]*10+[changed]*10
    output=list(scene_samples((Sample(i/10,im) for i,im in enumerate(images)),10))
    assert [s.t for s in output if s.cut]==[1.0]


def test_torso_anchor_does_not_move_with_outstretched_arm_box():
    def person(box):
        pose=[[.5,.5,.99] for _ in range(17)]
        return dict(id='a',box=box,confidence=.99,pose=pose)
    a=person([.2,.1,.7,.99]);b=person([.05,.1,.7,.99])
    CenterScorer().update([a],0);CenterScorer().update([b],0)
    assert a['features']['central']==b['features']['central']


def test_agent_annotation_api_persists_without_manual_confirmation(tmp_path):
    manager=Manager(tmp_path/'data');path=tmp_path/'v.mp4';make_video(path)
    with TestClient(create_app(manager,start_worker=False)) as client:
        identity=client.post('/api/jobs',files={'file':('unnamed.mp4',path.read_bytes())}).json()['id']
        job=manager.jobs[identity];manager.model=FakeModel();manager._analyze(job)
        context=client.get(f'/api/jobs/{identity}/agent-context').json()
        track=context['tracks'][0]['track_id']
        entry=dict(track_id=track,name='Example',start=.5,end=1.0,evidence='explicit_person_annotation',source_url='https://example.org/performance',source_note='Explicit name tag in original performance, associated with this position and interval.')
        response=client.put(f'/api/jobs/{identity}/annotations',json=dict(status='partial',annotations=[entry]))
        assert response.status_code==200
        assert response.json()['labels']=={}
        assert response.json()['annotations'][0]['name']=='Example'
        export=client.get(f'/api/jobs/{identity}/export').json()
        assert export['people_ranking'][0]['name']=='Example'
        assert export['people_ranking'][0]['seconds']==pytest.approx(.5)
        assert client.put(f'/api/jobs/{identity}/annotations',json=dict(status='complete',annotations=[dict(entry,end=100)])).status_code==422
        assert Manager(tmp_path/'data').jobs[identity].meta['annotations'][0]['name']=='Example'


def test_agent_worker_uses_json_input_without_shell(monkeypatch):
    import subprocess
    from types import SimpleNamespace
    from centerstage.agent_worker import work
    calls=[]
    class Response:
        def __init__(self,data):self.data=data
        def raise_for_status(self):pass
        def json(self):return self.data
    class Client:
        def __init__(self,**kw):pass
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def get(self,path):
            if path.endswith('/requests'):return Response({'requests':[dict(job_id='test',type='person_annotations',filename='$(do-not-execute).mp4')]})
            return Response({'tracks':[]})
        def put(self,path,json):calls.append((path,json));return Response({})
    def adapter(command,**kwargs):
        assert command==['my-agent','--json'] and kwargs['shell'] is False
        assert json.loads(kwargs['input'])['task']['filename']=='$(do-not-execute).mp4'
        return SimpleNamespace(returncode=0,stdout='{"status":"unresolved","annotations":[],"note":"No explicit source annotation"}')
    monkeypatch.setattr('centerstage.agent_worker.httpx.Client',Client)
    monkeypatch.setattr(subprocess,'run',adapter)
    work('http://127.0.0.1:8640',['my-agent','--json'],once=True)
    assert calls[0][0]=='/api/jobs/test/annotations'
    assert calls[0][1]['status']=='unresolved'

@pytest.mark.parametrize('fps',[10,15,30])
def test_center_runs_keep_tails_and_change_at_original_boundary(fps):
    from centerstage.scoring import CenterWindow
    # Two sustained runs followed by a genuinely unknown interval.
    frames=[dict(t=i/fps,end=(i+1)/fps,shot=0,centers=['a'] if i<fps else ['b'] if i<2*fps else []) for i in range(3*fps)]
    window=CenterWindow();result=[]
    for frame in frames:result+=window.feed(frame)
    result+=window.finish()
    assert [f['centers'] for f in result]==[f['centers'] for f in frames]
    assert [f['t'] for f in result]==[f['t'] for f in frames]


def test_center_confirmation_never_crosses_cuts_gaps_or_isolated_frames():
    from centerstage.scoring import CenterWindow
    frames=[dict(t=0,end=.1,shot=0,centers=['a']),
            dict(t=.1,end=.2,shot=1,centers=['a']),
            dict(t=.2,end=.3,shot=1,centers=[]),
            dict(t=.3,end=.4,shot=1,centers=['b']),
            dict(t=.5,end=.6,shot=1,centers=['b']),
            dict(t=.6,end=.7,shot=1,centers=['b'])]
    window=CenterWindow();result=[]
    for frame in frames:result+=window.feed(frame)
    result+=window.finish()
    assert [f['centers'] for f in result]==[[],[],[],[],['b'],['b']]


def test_optional_ocr_preparation_does_not_block_first_video(tmp_path,monkeypatch):
    import threading
    import centerstage.engine as engine
    preparing=threading.Event();release=threading.Event();finished=threading.Event()
    def slow_ocr(_):
        preparing.set();release.wait(3);return None
    monkeypatch.setenv('CENTERSTAGE_OCR','1')
    monkeypatch.setattr(engine,'prepare_model',lambda *args:tmp_path/'model.onnx')
    monkeypatch.setattr(engine,'load_model',lambda *args:FakeModel())
    monkeypatch.setattr(engine,'prepare_caption_reader',slow_ocr)
    manager=Manager(tmp_path);directory=manager.allocate();path=directory/'video.mp4';make_video(path)
    job=manager.create(path,'no-subtitles.mp4',inspect_video(path))
    original=manager._analyze
    def analyze(job):
        try:original(job)
        finally:finished.set()
    manager._analyze=analyze
    try:
        manager.start()
        assert preparing.wait(2)
        assert manager.model_status=='ready' and manager.caption_model_status=='preparing'
        assert finished.wait(2), 'C 位处理不应等待可选 OCR 模型准备'
        assert job.meta['status']=='complete'
        assert any(f['centers'] for f in job.frames)
        assert job.meta['caption_start_reason']=='preparing'
    finally:release.set()
