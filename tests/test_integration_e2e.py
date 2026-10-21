"""Portable end-to-end tests of the shipped API, using a real decoded video.

Model output is deterministic; these are contract tests, not accuracy scores.
The former test used nonexistent endpoints and mistook a roster for recognition.
"""
import csv
import io

from fastapi.testclient import TestClient
import pytest

from centerstage.app import create_app
from centerstage.engine import Manager
from test_engine import FakeModel, make_video


def test_upload_review_export_reload_and_media_bounds(tmp_path):
    source=tmp_path/'sample.mp4';make_video(source, count=48)
    manager=Manager(tmp_path/'data');manager.model=FakeModel()
    with TestClient(create_app(manager,start_worker=False)) as client:
        assert client.get('/api/jobs/missing').status_code==404
        response=client.post('/api/jobs',files={'file':('sample.mp4',source.read_bytes())},
                             data={'mode':'stream','analysis_fps':10})
        assert response.status_code==201
        job=manager.jobs[response.json()['id']];base='/api/jobs/'+job.meta['id']
        manager._analyze(job);job.save()
        assert job.meta['status']=='complete'
        context=client.get(base+'/agent-context').json()
        track=context['tracks'][0]['track_id']
        annotation=dict(track_id=track,name='Example',start=.5,end=1.5,
            evidence='explicit_person_annotation',source_url='https://example.org/labelled-source',
            source_note='Synthetic fixture with an explicit position and time annotation.')
        response=client.put(base+'/annotations',json=dict(status='partial',annotations=[annotation],
            mode='merge',base_revision=0,reviewed=context['review']))
        assert response.status_code==200
        all_frames=[];cursor=0
        while True:
            batch=client.get(base+f'/frames?after={cursor}').json()
            all_frames+=batch['frames'];cursor=batch['next']
            if cursor==batch['total']:break
        assert len(all_frames)==40
        for cutoff in (0,.25,.5,1.,1.5,3.999,4.,100.):
            query=f'?until={cutoff}&view=members'
            stats=client.get(base+'/statistics'+query).json()
            payload=client.get(base+'/export'+query).json()
            assert payload['statistics']==stats
            assert all(row['seconds']>0 for row in payload['ranking'])
            assert sum(row['equivalent_seconds'] for row in payload['ranking'])+payload['unknown_seconds']==pytest.approx(stats['covered'])
            exported=list(csv.DictReader(io.StringIO(client.get(base+'/export'+query+'&format=csv').text.lstrip('\ufeff'))))
            named=[r for r in exported if r['identity_status']=='named']
            assert len(named)==len(stats['rows'])
            if named:assert float(named[0]['center_seconds'])==pytest.approx(stats['rows'][0]['seconds'],abs=.001)
        restored=Manager(manager.data).jobs[job.meta['id']]
        assert restored.frames==job.frames and restored.meta['annotations']==[annotation]
        assert client.get(base+'/video',headers={'Range':'bytes=0-31'}).status_code==206
        assert client.get('/api/jobs').json()['jobs'][0]['id']==job.meta['id']


def test_invalid_options_and_runtime_config_do_not_mutate_active_service(tmp_path):
    source=tmp_path/'v.mp4';make_video(source)
    manager=Manager(tmp_path/'data')
    with TestClient(create_app(manager,start_worker=False)) as client:
        before=client.get('/api/config').json()
        assert before['inference_batch_size']==1 and before['read_only']
        for payload in ({'model':{'use_batch_inference':True}}, {'scoring':{'use_enhanced_scoring':True}}, []):
            assert client.post('/api/config',json=payload).status_code==409
        assert client.get('/api/config').json()==before
        assert client.get('/api/performance/stats').json()['jobs']==[]
        for option in ({'source_url':'https:broken'},{'analysis_fps':0},{'tracker':'invalid'},{'mode':'invalid'}):
            assert client.post('/api/jobs',files={'file':('v.mp4',source.read_bytes())},data=option).status_code==422
        assert not manager.jobs
