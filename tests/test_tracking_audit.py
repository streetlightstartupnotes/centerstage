from scripts.audit_tracking import summarize_frames
import pytest


def test_observed_duration_does_not_count_occlusion_gaps():
    frames=[dict(t=0,end=.1,shot=0,people=[{'id':'a'}],centers=['a']),
            dict(t=.1,end=5,shot=0,people=[],centers=[]),
            dict(t=5,end=5.1,shot=0,people=[{'id':'a'}],centers=['a']),
            dict(t=5.1,end=5.2,shot=1,people=[{'id':'b'}],centers=['b'])]
    report=summarize_frames(frames)
    assert report['tracks']==2 and report['shots']==2
    assert report['median_observed_seconds']==pytest.approx(.15)
    assert report['unknown_center_seconds']==pytest.approx(4.9)
    assert report['per_shot'][0]=={'shot':0,'tracks':1,'maximum_simultaneous':1}
    assert 'accuracy' not in report


def test_empty_track_audit_has_no_invented_people():
    report=summarize_frames([dict(t=0,end=1,shot=0,people=[],centers=[])])
    assert report['tracks']==0 and report['median_observations']==0
    assert report['median_observed_seconds']==0
    assert report['unknown_center_seconds']==1
