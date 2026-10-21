import json
import logging
import math
import os
import queue
import shutil
import threading
import time
import uuid
from pathlib import Path
from copy import deepcopy

import av

from .config import DATA, MAX_DURATION, SCHEMA_VERSION
from .model import prepare_model, load_model
from .scoring import totals
from .pipeline import AnalysisPipeline, PipelineConfig
from .rosters import candidate_roster
from .captions import prepare_caption_reader, CaptionWorker
from .video import samples, scene_samples, DecodeProgress
from .annotations import annotation_due, apply_annotations, annotations_from_member_credits
from .annotations import AnnotationResult, name_status


def atomic_json(path, data):
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(data, ensure_ascii=False, allow_nan=False), encoding="utf-8")
    temp.replace(path)


def inspect_video(path):
    with av.open(str(path)) as container:
        if not container.streams.video:
            raise ValueError("文件中没有可解码的视频轨道")
        s = container.streams.video[0]
        duration = float(s.duration*s.time_base) if s.duration else (container.duration or 0)/av.time_base
        if not math.isfinite(duration) or duration <= 0 or duration > MAX_DURATION:
            raise ValueError("第一版支持最长 30 分钟、时长可读取的视频")
        if s.width*s.height > 3840*2160:
            raise ValueError("请导入 4K 或以下分辨率的视频")
        fps = float(s.average_rate or 30)
        if min(s.width, s.height) <= 0 or not math.isfinite(fps) or fps <= 0:
            raise ValueError('视频尺寸或帧率无效')
        return {"width":s.width,"height":s.height,"duration":duration,"fps":fps,"codec":s.codec_context.name}


def validate_frame(frame, previous_end=0.0, duration=None):
    """Persist only ordered, finite, half-open media intervals with live centers."""
    start, end = frame['t'], frame['end']
    if (not math.isfinite(start) or not math.isfinite(end) or start < 0 or end <= start
            or start < previous_end - 1e-6 or (duration is not None and end > duration + 1e-5)):
        raise ValueError('无效、重叠或越界的分析时间区间')
    ids = [p['id'] for p in frame['people']]
    if len(set(ids)) != len(ids) or len(set(frame['centers'])) != len(frame['centers']) or not set(frame['centers']) <= set(ids):
        raise ValueError('C 位必须对应当前画面中的唯一轨迹')
    for person in frame['people']:
        box = person['box']
        if (len(box) != 4 or not all(math.isfinite(v) and 0 <= v <= 1 for v in box)
                or box[2] <= box[0] or box[3] <= box[1]):
            raise ValueError('无效的人物框')
    # Also reject non-finite optional pose/feature fields before persistence.
    json.dumps(frame, allow_nan=False)


class Job:
    def __init__(self, directory, metadata):
        self.directory = directory
        self.meta = metadata
        self.frames = []
        self.tracks = {}
        self.lock = threading.RLock()
        self.cancel = threading.Event()
        self.removed = False
        self.active = False

    def save(self):
        with self.lock:
            if self.removed: return
            atomic_json(self.directory/"job.json", self.meta)

    def snapshot(self):
        with self.lock:
            data = deepcopy(self.meta)
            data["frame_count"] = len(self.frames)
            data.pop("people_count",None)  # Legacy field counted fragments, never actual members.
            data["track_count"] = len(data.get("track_ids",[]))
            data['annotation_pending']=annotation_due(self)
            data['name_status']=name_status(self.meta)
            return data

    def append(self, frame, sink):
        with self.lock:
            validate_frame(frame, self.frames[-1]['end'] if self.frames else 0, self.meta['video']['duration'])
            encoded = json.dumps(frame, ensure_ascii=False, allow_nan=False)
            sink.write(encoded+"\n")
            self.frames.append(frame)
            self.index_frame(frame)
            self.meta["confirmed_until"] = frame["end"]
            self.meta["track_count"] = len({p["id"] for p in frame["people"]} | set(self.meta.get("track_ids",[])))
            self.meta["track_ids"] = sorted(set(self.meta.get("track_ids",[])) | {p["id"] for p in frame["people"]})

    def index_frame(self, frame):
        for person in frame['people']:
            row=self.tracks.setdefault(person['id'],dict(track_id=person['id'],start=frame['t'],
                end=frame['end'],sample_time=frame['t'],box=person['box']))
            row['end']=frame['end']


class Manager:
    def __init__(self, data=DATA):
        self.data=Path(data)
        self.data.mkdir(parents=True,exist_ok=True)
        (self.data/"jobs").mkdir(exist_ok=True)
        self.jobs={}
        self.queue=queue.Queue()
        self.model=None
        self.caption_binary=None
        self.caption_model_status="starting"
        self.model_status="starting"
        self.model_message="准备本地分析引擎"
        self.model_error=None
        self.start_lock=threading.Lock()
        self.started=False
        self.stopping=False
        self.worker=None
        for path in (self.data/"jobs").glob("*/job.json"):
            try:
                job=Job(path.parent,json.loads(path.read_text()))
                frame_path=path.parent/"frames.jsonl"
                damaged = False
                if frame_path.exists():
                    with frame_path.open(encoding='utf-8') as source:
                        for line in source:
                            try:
                                frame=json.loads(line)
                                validate_frame(frame, job.frames[-1]['end'] if job.frames else 0, job.meta['video']['duration'])
                                job.frames.append(frame)
                                job.index_frame(frame)
                            except (ValueError, TypeError, KeyError):
                                damaged = True
                                break
                recovered_end = job.frames[-1]['end'] if job.frames else 0
                if (damaged or recovered_end + .001 < job.meta.get('confirmed_until', 0)
                        or (job.meta['status'] == 'complete' and recovered_end + .001 < job.meta['video']['duration'])):
                    job.meta.update(status='interrupted', message='分析文件不完整；仅保留已校验区间，请重新分析剩余视频', recovery_warning=True)
                elif job.meta["status"] not in ("complete","cancelled","failed"):
                    job.meta.update(status="interrupted",message="上次服务中断；可查看已完成结果或重新分析")
                job.meta['track_ids'] = sorted(job.tracks)
                job.meta['track_count'] = len(job.tracks)
                job.meta['ranking'], job.meta['unknown_seconds'] = totals(job.frames)
                job.meta["confirmed_until"]=recovered_end
                self.jobs[job.meta["id"]]=job
            except (ValueError,KeyError,OSError):
                continue

    def start(self):
        with self.start_lock:
            if self.started: return
            self.started=True
            self.worker=threading.Thread(target=self._loop, daemon=True, name="centerstage-worker")
            self.worker.start()

    def stop(self):
        """Release the single worker on app shutdown; retain confirmed frames."""
        with self.start_lock:
            if self.stopping:return
            self.stopping=True
            for job in self.jobs.values():
                if job.meta['status'] not in ('complete','failed','cancelled','interrupted'):
                    job.cancel.set()
            if self.worker:self.queue.put(None)
        if self.worker:self.worker.join(timeout=5)

    def _loop(self):
        try:
            self.model_status="loading"
            path=prepare_model(self.data/"models",lambda text:setattr(self,"model_message",text))
            self.model_message="模型预热中"
            self.model=load_model(path, os.environ.get("CENTERSTAGE_PROVIDER","auto"))
            self.model_status="ready"
            self.model_message="RTMO-s 已就绪 · 本地处理"
            # Optional source text must never hold the center-analysis queue.
            self.caption_model_status="preparing" if os.environ.get('CENTERSTAGE_OCR','1')!='0' else "disabled"
            if self.caption_model_status=="preparing":
                threading.Thread(target=self._prepare_captions,daemon=True,name="centerstage-ocr-prepare").start()
        except Exception as exc:
            self.model_status="failed"
            self.model_error=str(exc)
            self.model_message="模型准备失败，请检查网络或重新启动"
        while True:
            job=self.queue.get()
            if job is None:
                self.queue.task_done()
                return
            try:
                with job.lock:
                    removed=job.removed
                    if not removed: job.active=True
                if removed:
                    pass
                elif job.cancel.is_set():
                    with job.lock:
                        if not job.removed: job.meta.update(status="cancelled",message="任务已取消")
                elif self.model is None:
                    raise RuntimeError(self.model_error or "模型不可用")
                else:
                    self._analyze(job)
            except Exception as exc:
                with job.lock:
                    if not job.removed: job.meta.update(status="failed",message=str(exc))
            finally:
                try:
                    if hasattr(job,'caption_worker'):job.caption_worker.close()
                    with job.lock:
                        removed=job.removed
                        job.active=False
                    if removed: self._discard(job)
                    else: job.save()
                except Exception:
                    with job.lock:
                        if not job.removed: job.meta.update(status='failed', message='无法保存任务结果，请检查本地存储')
                    logging.exception('Failed to finalize a local analysis job')
                finally:
                    self.queue.task_done()

    def _prepare_captions(self):
        try:
            self.caption_binary=prepare_caption_reader(self.data/'models/ocr')
            self.caption_model_status='ready' if self.caption_binary else 'unavailable'
        except Exception:
            self.caption_model_status='unavailable'

    def create(self, path, name, info, mode="stream", source_url="", analysis_fps=10, tracker="ocsort", group_id="auto"):
        identity=path.parent.name
        meta={"schema_version":SCHEMA_VERSION,"id":identity,"filename":name,"media_name":path.name,
              "created_at":time.time(),"status":"queued","message":"等待分析引擎","video":info,
              "confirmed_until":0.0,"analysis_fps":analysis_fps,"tracker":tracker,"mode":mode,
              "elapsed":0.0,"speed":0.0,"first_result_seconds":None,"ready_seconds":None,
              "labels":{},"source_url":source_url,"roster":[],"source_task":"pending",
              "annotations":[],"annotation_status":"pending","annotation_note":"",
              "annotation_revision":0,"roster_revision":0,
              "method":"RTMO-s + adaptive shots + tracking + visual-center baseline v4","track_ids":[]}
        group,roster=candidate_roster(name,group_id)
        meta.update(group=group,roster=roster,source_task="complete" if roster else meta["source_task"])
        job=Job(path.parent,meta); job.save()
        self.jobs[identity]=job
        self.queue.put(job)
        return job

    def delete(self, identity):
        job=self.jobs.get(identity)
        if job is None: return False
        with job.lock:
            job.removed=True
            job.cancel.set()
            self.jobs.pop(identity, None)
            active=job.active
        if not active: self._discard(job)
        return True

    def _discard(self, job):
        directory=job.directory.resolve()
        root=(self.data/"jobs").resolve()
        if directory.parent!=root or not directory.is_dir(): return
        shutil.rmtree(directory, ignore_errors=True)

    def allocate(self):
        path=self.data/"jobs"/uuid.uuid4().hex
        path.mkdir()
        return path

    def _analyze(self, job):
        started=time.perf_counter()
        meta=job.meta
        with job.lock:meta.update(status="analyzing",message="正在提前分析")
        info=meta["video"]
        sample_rate=min(meta["analysis_fps"],info["fps"])
        config=PipelineConfig(sample_rate=sample_rate,tracker=meta['tracker'])
        pipeline=AnalysisPipeline(config)
        with job.lock:meta['pipeline']=config.metadata()
        caption_worker=CaptionWorker(self.caption_binary,job) if self.caption_binary else None
        if caption_worker:job.caption_worker=caption_worker
        with job.lock:
            meta['caption_status']='reading' if caption_worker else 'unavailable'
            meta['caption_start_reason']='ready' if caption_worker else self.caption_model_status
        last_save=0; shot=0
        path=job.directory/meta["media_name"]
        decoded = DecodeProgress()
        source=samples(path,sample_rate,info['fps'],captions=caption_worker is not None,cancelled=job.cancel.is_set,progress=decoded)
        with (job.directory/"frames.jsonl").open("w",encoding="utf-8") as sink:
            for sample in scene_samples(source,sample_rate):
                if job.cancel.is_set(): break
                timestamp,image=sample.t,sample.image
                if caption_worker and sample.caption is not None:
                    caption_worker.submit(timestamp,sample.caption)
                if sample.cut:shot+=1
                boxes, confidence, poses=self.model.predict(image)
                h,w=image.shape[:2]
                for settled in pipeline.feed(timestamp,shot,w,h,boxes,confidence,poses,image=image):
                    job.append(settled,sink)
                elapsed=time.perf_counter()-started
                with job.lock:
                    meta["elapsed"]=round(elapsed,3)
                    meta["speed"]=round(meta["confirmed_until"]/max(elapsed,.001),3)
                    if job.frames and meta["first_result_seconds"] is None: meta["first_result_seconds"]=round(elapsed,3)
                    if meta["confirmed_until"]>=3 and meta["ready_seconds"] is None: meta["ready_seconds"]=round(elapsed,3)
                    if meta["confirmed_until"]>=3: meta["message"]="结果持续更新，可开始播放"
                if elapsed-last_save>=.5:
                    with job.lock:meta['appearance_links']=pipeline.linker.links()
                    sink.flush(); job.save(); last_save=elapsed
            final_end = min(info['duration'], decoded.end)
            for settled in pipeline.finish(None if job.cancel.is_set() else final_end):
                job.append(settled,sink)
            sink.flush()
        if caption_worker:caption_worker.close()
        with job.lock:
            meta['appearance_links']=pipeline.linker.links()
            meta['appearance_conflicts']=pipeline.linker.conflicts
            meta["elapsed"]=round(time.perf_counter()-started,3)
            meta["speed"]=round(meta["confirmed_until"]/max(meta["elapsed"],.001),3)
            meta["status"]="cancelled" if job.cancel.is_set() else "complete"
            meta["message"]="已保留取消前的结果" if job.cancel.is_set() else "分析完成"
            if not job.cancel.is_set() and final_end + .001 < info['duration']:
                meta.update(status='interrupted', message='视频解码提前结束，未解码部分不计入 C 位时间')
            if meta["ready_seconds"] is None and job.frames: meta["ready_seconds"]=meta["elapsed"]
            ranking,unknown=totals(job.frames)
            meta["ranking"]=ranking; meta["unknown_seconds"]=unknown
            if meta['status']=='complete' and not meta.get('annotations'):
                credited=annotations_from_member_credits(
                    job.frames, meta.get('captions') or [], meta.get('roster') or [],
                    meta.get('source_url') or '', meta.get('appearance_links') or {})
                if credited:
                    try:
                        apply_annotations(job, AnnotationResult(
                            status='partial', annotations=credited,
                            note='画面成员名条与唯一视觉 C 位重合，名字记在对应轨迹上。'))
                    except ValueError as exc:
                        meta['annotation_note']=f'成员名条未写入：{exc}'
