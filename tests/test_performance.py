"""Bounded-memory and queue invariants. Real hardware timing is a separate run."""
import io
import threading
from types import SimpleNamespace

import numpy as np
import pytest

from centerstage.captions import CaptionWorker
from centerstage.engine import Job
from centerstage.pipeline import AnalysisPipeline, PipelineConfig


def test_center_lookahead_remains_bounded_for_long_input():
    pipeline=AnalysisPipeline(PipelineConfig(10,garment_matching=False))
    output=0
    for i in range(6000):
        output+=len(pipeline.feed(i/10,0,640,360,[],[],[]))
        assert len(pipeline.window.pending)<=4
        assert len(pipeline.window.recent)<=4
    output+=len(pipeline.finish(600))
    assert output==6000


def test_slow_optional_ocr_has_bounded_queue_and_retains_drop_count(tmp_path):
    entered=threading.Event();release=threading.Event()
    def reader(_):
        entered.set();assert release.wait(5)
        return SimpleNamespace(txts=np.array(['[Example]']),scores=np.array([.99]))
    job=Job(tmp_path,dict(video={'duration':100},roster=[{'name':'Example'}]))
    worker=CaptionWorker(reader,job)
    try:
        image=np.zeros((16,16,3),np.uint8)
        worker.submit(0,image);assert entered.wait(2)
        for i in range(1,100):worker.submit(i,image)
        assert worker.queue.qsize()==2
        assert job.meta['caption_dropped']==97
    finally:
        release.set();worker.close()
    assert job.meta['caption_status']=='partial'
    assert len(job.meta['caption_text'])==3
    assert (tmp_path/'job.json').exists()


def test_failed_frame_persistence_cannot_advance_confirmed_time(tmp_path):
    class FullDisk(io.StringIO):
        def write(self,_):raise OSError('disk full')
    job=Job(tmp_path,dict(video={'duration':1},confirmed_until=0))
    with pytest.raises(OSError):job.append(dict(t=0,end=1,shot=0,people=[],centers=[]),FullDisk())
    assert job.frames==[] and job.meta['confirmed_until']==0 and job.tracks=={}
