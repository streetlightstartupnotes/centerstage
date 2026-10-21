"""Names require evidence; detection/roster coverage is not identification accuracy."""
import copy
import json

import pytest
from fastapi.testclient import TestClient

from centerstage.annotations import label_at, name_status
from centerstage.app import create_app
from centerstage.engine import Manager
from centerstage.statistics import center_statistics
from centerstage.智能识别引擎 import SmartIdentifier
from centerstage.智能识别集成 import auto_identify_members, apply_names_to_frames


def test_roster_and_high_confidence_guess_never_establish_a_name():
    labels = {'a': {'name': 'Roster A', 'evidence': 'auto_identified', 'confidence': .99}}
    assert label_at('a', .5, labels) is None
    status = name_status({'labels': labels, 'roster': [{'name': 'Roster A'}]})
    assert status['state'] == 'unresolved'
    assert status['supported_name_count'] == 0
    assert status['unsupported_label_count'] == 1


def test_supported_annotations_stay_scoped_and_manual_corrections_survive():
    labels = {'a': {'name': 'Wrong guess', 'evidence': 'auto_identified'},
              'b': {'name': 'Correction', 'evidence': 'user_confirmed'}}
    annotations = [dict(track_id='a', start=1, end=2, name='Source label',
                        evidence='explicit_person_annotation',
                        source_url='https://example.org/annotated-source',
                        source_note='The source explicitly labels track a in this interval.')]
    assert label_at('a', .99, labels, annotations) is None
    assert label_at('a', 1.5, labels, annotations)['name'] == 'Source label'
    assert label_at('a', 2, labels, annotations) is None
    assert label_at('b', 1.5, labels, annotations)['name'] == 'Correction'
    frames = [dict(t=0, end=3, centers=['a'], people=[dict(id='a')])]
    stats = center_statistics(frames, labels, annotations)
    assert next(r for r in stats['rows'] if r['named'])['seconds'] == 1
    assert stats['unbound'] == 2


def test_retired_endpoint_does_not_write_guesses_and_exports_agree(tmp_path):
    manager = Manager(tmp_path)
    directory = manager.allocate()
    path = directory / 'video.mp4'
    path.touch()
    job = manager.create(path, 'synthetic.mp4', dict(duration=2, width=320, height=240, fps=10))
    job.frames = [dict(t=0, end=2, shot=0, centers=['a'], people=[dict(id='a')])]
    job.meta.update(status='complete', track_ids=['a'], labels={
        'a': dict(name='Guessed', evidence='auto_identified', confidence=.99)})
    before = copy.deepcopy((job.meta, job.frames))
    with TestClient(create_app(manager, start_worker=False)) as client:
        base = f'/api/jobs/{job.meta["id"]}'
        response = client.post(base + '/auto-identify')
        assert response.status_code == 409
        assert response.json()['success'] is False
        assert response.json()['code'] == 'name_evidence_required'
        assert (job.meta, job.frames) == before
        snapshot = client.get(base).json()
        assert snapshot['name_status']['supported_name_count'] == 0
        assert snapshot['labels']['a']['name'] == 'Guessed'  # Raw record retained for audit.
        stats = client.get(base + '/statistics').json()
        exported = client.get(base + '/export').json()
        assert exported['statistics'] == stats
        assert stats['rows'][0]['named'] is False
        assert stats['rows'][0]['name'] != 'Guessed'
        assert 'Guessed' not in client.get(base + '/export?format=csv').text


def test_old_guess_cache_is_preserved_but_cannot_reapply_names(tmp_path):
    identifier = SmartIdentifier(tmp_path)
    path = tmp_path / 'job_smart_id.json'
    old = json.dumps({'roster': ['Roster A'], 'mappings': {'a': 'Roster A'},
                      'confidence': {'a': .95}})
    path.write_text(old)
    assert identifier.load('job') is False
    assert identifier.get_all_mappings() == {}
    assert path.read_text() == old
    identifier.manual_correction('a', 'Actual correction')
    identifier.save('corrected')
    restored = SmartIdentifier(tmp_path)
    assert restored.load('corrected') is True
    assert restored.get_member_name('a') == 'Actual correction'


def test_legacy_automatic_entry_points_fail_before_mutating(tmp_path):
    identifier = SmartIdentifier(tmp_path)
    identifier.roster = ['Roster A', 'Roster B']
    with pytest.raises(ValueError, match='真实姓名'):
        identifier.auto_match_tracks({'a': dict(appearances=1000, center_time=200)})
    assert identifier.track_mappings == {}
    assert identifier.confidence_scores == {}
    with pytest.raises(ValueError, match='停用'):
        auto_identify_members(None, None)
    with pytest.raises(ValueError, match='停用'):
        apply_names_to_frames(None, identifier)
