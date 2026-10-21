"""Regression cases discovered in the whole-project timing/logic audit."""
import io
import json
from copy import deepcopy

import pytest

from centerstage.annotations import AnnotationResult, apply_annotations, label_at
from centerstage.engine import Manager, validate_frame
from centerstage.scoring import totals, named_totals
from centerstage.statistics import center_statistics
from test_engine import FakeModel, make_video


def analyzed(tmp_path):
    manager=Manager(tmp_path);directory=manager.allocate();path=directory/'video.mp4';make_video(path)
    job=manager.create(path,'fixture.mp4',dict(width=320,height=240,fps=12,duration=2))
    manager.model=FakeModel();manager._analyze(job);job.save()
    return manager,job


@pytest.mark.parametrize('damage',['truncated','overlap','unknown_center','nonfinite','shortened'])
def test_restore_retains_valid_prefix_and_cannot_claim_complete(tmp_path,damage):
    manager,job=analyzed(tmp_path)
    path=job.directory/'frames.jsonl';lines=path.read_text().splitlines()
    frame=json.loads(lines[6])
    if damage=='truncated':tail='{"t":'
    elif damage=='overlap':frame['t']=0;tail=json.dumps(frame)
    elif damage=='unknown_center':frame['centers']=['absent'];tail=json.dumps(frame)
    elif damage=='nonfinite':frame['people'][0]['pose'][0][0]=float('nan');tail=json.dumps(frame)
    else:tail=''
    content='\n'.join(lines[:6])+ '\n'+tail
    path.write_text(content)
    restored=Manager(tmp_path).jobs[job.meta['id']]
    assert len(restored.frames)==6
    assert restored.meta['status']=='interrupted' and restored.meta['recovery_warning']
    assert restored.meta['confirmed_until']==restored.frames[-1]['end']
    assert restored.meta['track_ids']==sorted(restored.tracks)
    assert restored.meta['unknown_seconds']==totals(restored.frames)[1]
    assert path.read_text()==content  # Diagnosis must not overwrite the damaged evidence.


def test_snapshot_isolated_from_concurrent_annotation_mutation(tmp_path):
    _,job=analyzed(tmp_path)
    snapshot=job.snapshot()
    job.meta['roster'].append({'name':'Later','source':'https://example.org'})
    assert snapshot['roster']==[]


def test_declared_duration_cannot_stretch_last_detection_over_undecoded_video(tmp_path):
    manager=Manager(tmp_path);directory=manager.allocate();path=directory/'video.mp4';make_video(path)
    job=manager.create(path,'wrong-header.mp4',dict(width=320,height=240,fps=12,duration=10))
    manager.model=FakeModel();manager._analyze(job)
    assert job.meta['status']=='interrupted'
    assert job.frames[-1]['end']==pytest.approx(2)
    assert sum(f['end']-f['t'] for f in job.frames)==pytest.approx(2)


def test_invalid_append_never_advances_timeline(tmp_path):
    _,job=analyzed(tmp_path);before=deepcopy((job.frames,job.meta));sink=io.StringIO()
    with pytest.raises(ValueError):job.append(dict(t=1,end=1.1,centers=[],people=[]),sink)
    assert (job.frames,job.meta)==before and sink.getvalue()==''


def test_same_clothing_group_never_deduplicates_cooccurring_centers():
    frames=[dict(t=0,end=1,centers=['a','b'],people=[])]
    links={i:dict(group_id='g0001',tentative=True) for i in ('a','b')}
    result=center_statistics(frames,{},appearance_links=links)
    assert len(result['rows'])==2
    assert [r['equivalent_seconds'] for r in result['rows']]==[.5,.5]
    assert result['unbound']==1


def test_no_zero_time_rows_and_no_duplicate_raw_center_time():
    frames=[dict(t=0,end=1,centers=['a','a']),dict(t=1,end=2,centers=['b'])]
    result,unknown=totals(frames,until=.5)
    assert result==[dict(id='a',seconds=.5,equivalent_seconds=.5)] and unknown==0


@pytest.mark.parametrize('evidence',[None,'auto_identified','printed_subtitle'])
def test_untrusted_stored_annotations_cannot_bypass_evidence_check(evidence):
    annotation=dict(track_id='a',start=0,end=1,name='Guess',evidence=evidence)
    assert label_at('a',.5,{},[annotation]) is None
    frames=[dict(t=0,end=1,people=[],centers=['a'])]
    assert named_totals(frames,{},annotations=[annotation])[0]==[]
    assert not center_statistics(frames,{},[annotation])['rows'][0]['named']


def test_annotation_cannot_cover_absent_track_or_unreviewed_gap(tmp_path):
    _,job=analyzed(tmp_path)
    track=job.frames[0]['people'][0]['id']
    job.frames[5]['people']=[];job.frames[5]['centers']=[]
    payload=AnnotationResult(status='partial',annotations=[dict(track_id=track,name='Example',start=0,end=1,
        evidence='explicit_person_annotation',source_url='https://example.org/annotated',
        source_note='Synthetic fixture; this span deliberately crosses a missing observation.')])
    with pytest.raises(ValueError,match='空隙'):apply_annotations(job,payload)
    assert job.meta['annotations']==[]


def test_api_documented_version_and_package_agree():
    import tomllib
    from pathlib import Path
    from centerstage import __version__
    assert __version__==tomllib.loads((Path(__file__).parents[1]/'pyproject.toml').read_text())['project']['version']


def test_worker_survives_final_save_error_and_releases_queue(tmp_path,monkeypatch):
    import threading
    import centerstage.engine as engine
    monkeypatch.setenv('CENTERSTAGE_OCR','0')
    monkeypatch.setattr(engine,'prepare_model',lambda *args:tmp_path/'model')
    monkeypatch.setattr(engine,'load_model',lambda *args:FakeModel())
    manager=Manager(tmp_path);jobs=[];finished=threading.Event()
    for i in range(2):
        directory=manager.allocate();path=directory/'video.mp4';path.touch()
        jobs.append(manager.create(path,f'{i}.mp4',dict(width=320,height=240,fps=10,duration=1)))
    def analyze(job):
        job.meta['status']='complete'
        if job is jobs[1]:finished.set()
    manager._analyze=analyze
    def fail_save():raise OSError('fixture disk error')
    jobs[0].save=fail_save
    manager.start()
    try:assert finished.wait(2), 'One failed save must not kill all later video jobs'
    finally:manager.stop()
    assert jobs[0].meta['status']=='failed' and jobs[1].meta['status']=='complete'
    assert manager.queue.unfinished_tasks==0 and not manager.worker.is_alive()


def test_invalid_adapter_output_does_not_crash_or_write_names(monkeypatch,capsys):
    from types import SimpleNamespace
    from centerstage.agent_worker import work
    class Response:
        def __init__(self,value):self.value=value
        def json(self):return self.value
        def raise_for_status(self):pass
    class Client:
        def __init__(self,**kwargs):pass
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def get(self,path):return Response({'requests':[{'job_id':'x','type':'person_annotations'}]} if path.endswith('/requests') else {'review':{}})
        def put(self,*args,**kwargs):pytest.fail('Invalid output must never be submitted')
    monkeypatch.setattr('centerstage.agent_worker.httpx.Client',Client)
    monkeypatch.setattr('centerstage.agent_worker.subprocess.run',lambda *a,**kw:SimpleNamespace(returncode=0,stdout='["invalid"]'))
    work('http://127.0.0.1',['adapter'],once=True)
    assert json.loads(capsys.readouterr().out)['status']=='retry_later'
