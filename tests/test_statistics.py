import json
import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from centerstage.app import create_app
from centerstage.engine import Manager
from centerstage.statistics import center_statistics

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = json.loads((ROOT/'tests/data/statistics.json').read_text())


def test_browser_and_export_agree_at_every_boundary():
    script = """
import fs from 'node:fs';
import {CenterStatistics} from './centerstage/static/statistics.js';
const f=JSON.parse(fs.readFileSync('tests/data/statistics.json','utf8'));
const s=new CenterStatistics(f.labels,f.annotations);s.append(f.frames);
console.log(JSON.stringify([0,.5,1,2,3,4,4.5,5,5.5,6,7,8,9,9.5,10,11,99].map(t=>s.at(t))));
"""
    snapshots=json.loads(subprocess.run(['node','--input-type=module','-e',script],cwd=ROOT,check=True,capture_output=True,text=True).stdout)
    for t,js in zip([0,.5,1,2,3,4,4.5,5,5.5,6,7,8,9,9.5,10,11,99],snapshots):
        py=center_statistics(FIXTURE['frames'],FIXTURE['labels'],FIXTURE['annotations'],t)
        assert py == js


def test_statistics_api_and_csv_include_unnamed_tracks_and_honor_cutoff(tmp_path):
    manager=Manager(tmp_path)
    directory=manager.allocate();path=directory/'video.mp4';path.touch()
    job=manager.create(path,'synthetic.mp4',dict(duration=11,width=320,height=240,fps=10))
    job.frames=FIXTURE['frames'];job.meta['labels']=FIXTURE['labels'];job.meta['annotations']=FIXTURE['annotations']
    with TestClient(create_app(manager,start_worker=False)) as client:
        prefix=f"/api/jobs/{job.meta['id']}"
        stats=client.get(prefix+'/statistics?until=4').json()
        assert stats['rows'][0]['seconds']==3
        assert stats['rows'][1]['name']=='轨迹片段 002'
        exported=client.get(prefix+'/export?until=4').json()
        assert exported['statistics']==stats
        csv=client.get(prefix+'/export?format=csv&until=4').text
        assert '轨迹片段 002' in csv and 'anonymous_track' in csv and 'Sample B' not in csv
        for bad in ('nan','inf','-1'):
            assert client.get(prefix+f'/statistics?until={bad}').status_code==422
            assert client.get(prefix+f'/export?until={bad}').status_code==422


def test_tentative_garment_groups_match_browser_and_do_not_propagate_names():
    frames=[dict(t=0,end=1,centers=['a'],people=[dict(id='a')]),dict(t=1,end=2,centers=['b'],people=[dict(id='b')])]
    links={key:dict(group_id='g0001',tentative=True) for key in ('a','b')}
    result=center_statistics(frames,{},appearance_links=links)
    assert len(result['rows'])==1 and result['rows'][0]['seconds']==2
    assert result['rows'][0]['association']=='garment_similarity'
    assert result['rows'][0]['named'] is False
    labels={'a':dict(name='Source label',evidence='user_confirmed')}
    result=center_statistics(frames,labels,appearance_links=links)
    assert len(result['rows'])==2  # Garments cannot extend a real-name annotation.
    script="import {CenterStatistics} from './centerstage/static/statistics.js';const data=JSON.parse(process.argv[1]);const s=new CenterStatistics(data.labels,[],data.links);s.append(data.frames);console.log(JSON.stringify(s.at(2)));"
    actual=json.loads(subprocess.run(['node','--input-type=module','-e',script,json.dumps(dict(frames=frames,links=links,labels=labels))],cwd=ROOT,check=True,capture_output=True,text=True).stdout)
    assert actual==result


def test_garment_group_switch_export_and_restart(tmp_path):
    manager=Manager(tmp_path);directory=manager.allocate();path=directory/'video.mp4';path.touch()
    job=manager.create(path,'synthetic.mp4',dict(duration=2,width=320,height=240,fps=10))
    with (directory/'frames.jsonl').open('w') as sink:
        for i,key in enumerate(('a','b')):
            job.append(dict(t=i,end=i+1,shot=i,centers=[key],people=[dict(id=key,box=[.3,.1,.7,.9])]),sink)
    job.meta.update(status='complete',appearance_links={key:dict(group_id='g0001',tentative=True,evidence='garment_similarity') for key in ('a','b')})
    job.save();restored=Manager(tmp_path)
    with TestClient(create_app(restored,start_worker=False)) as client:
        base=f'/api/jobs/{job.meta["id"]}'
        combined=client.get(base+'/statistics').json()
        assert len(combined['rows'])==1 and combined['rows'][0]['seconds']==2
        separate=client.get(base+'/statistics?appearance=false').json()
        assert len(separate['rows'])==2
        assert 'tentative_garment_group' in client.get(base+'/export?format=csv').text
        assert 'tentative_garment_group' not in client.get(base+'/export?format=csv&appearance=false').text
        assert client.get(base+'/export?appearance=false').json()['statistics']==separate


def test_member_view_and_csv_do_not_turn_fragments_into_people(tmp_path):
    manager=Manager(tmp_path);directory=manager.allocate();path=directory/'video.mp4';path.touch()
    job=manager.create(path,'synthetic.mp4',dict(duration=2,width=320,height=240,fps=10))
    job.frames=[dict(t=i/10,end=(i+1)/10,centers=[f'left-{i}',f'right-{i}'],people=[]) for i in range(20)]
    with TestClient(create_app(manager,start_worker=False)) as client:
        base=f'/api/jobs/{job.meta["id"]}'
        assert len(client.get(base+'/statistics').json()['rows'])==40
        members=client.get(base+'/statistics?view=members').json()
        assert members['rows']==[]
        assert members['unbound']==pytest.approx(2)
        assert client.get(base+'/export?view=members').json()['statistics']==members
        csv=client.get(base+'/export?format=csv&view=members').text
        assert '轨迹片段' not in csv and '人物 ' not in csv
        assert '未对应姓名的 C 位区间,2.0,,0,unresolved_interval' in csv
        assert client.get(base+'/statistics?view=invalid').status_code==422
        job.meta['labels']={'left-1':dict(name='Source label',evidence='user_confirmed')}
        assert client.get(base+'/statistics?view=members&until=0.1').json()['rows']==[]
        named=client.get(base+'/statistics?view=members').json()['rows']
        assert len(named)==1 and named[0]['name']=='Source label'
        assert named[0]['seconds']==pytest.approx(.1)
