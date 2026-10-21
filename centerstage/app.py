import csv
import io
import json
import math
import shutil
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal
from urllib.parse import urlparse

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, model_validator
from starlette.concurrency import run_in_threadpool
from starlette.middleware.trustedhost import TrustedHostMiddleware

from .config import MAX_UPLOAD, get_config
from .engine import Manager, inspect_video
from .scoring import totals, named_totals
from .statistics import center_statistics, member_statistics
from .rosters import CATALOGS
from .annotations import AnnotationResult, AnnotationConflict, apply_annotations, agent_requests, review_scope, name_status
from .captions import refresh_caption_hints


class Label(BaseModel):
    name: str = Field(max_length=80)


class RosterEntry(BaseModel):
    name: str = Field(min_length=1,max_length=80)
    source: str = Field(max_length=2000)

    @model_validator(mode='after')
    def validate_entry(self):
        self.name = self.name.strip()
        parsed = urlparse(self.source)
        if not self.name or parsed.scheme not in ('http', 'https') or not parsed.netloc:
            raise ValueError('成员姓名不能为空，来源必须是完整的 HTTP 或 HTTPS 链接')
        return self


class Roster(BaseModel):
    members: list[RosterEntry] = Field(max_length=50)


class JobTitle(BaseModel):
    title: str = Field(min_length=1, max_length=200)

    @model_validator(mode='after')
    def clean_title(self):
        self.title=' '.join(self.title.split())
        if not self.title:
            raise ValueError('标题不能为空')
        return self


def create_app(manager=None, start_worker=True):
    manager=manager or Manager()
    @asynccontextmanager
    async def lifespan(app):
        if start_worker: manager.start()
        try:
            yield
        finally:
            if start_worker: await run_in_threadpool(manager.stop)

    app=FastAPI(title="Centerstage local API",version="0.2.0",lifespan=lifespan)
    app.state.manager=manager
    app.add_middleware(TrustedHostMiddleware,allowed_hosts=["127.0.0.1","localhost","[::1]","testserver"])

    @app.middleware("http")
    async def local_guard(request:Request,call_next):
        origin=request.headers.get("origin")
        if origin and urlparse(origin).netloc != request.headers.get("host"):
            return JSONResponse({"detail":"只接受当前本地页面的请求"},status_code=403)
        response=await call_next(request)
        response.headers["X-Content-Type-Options"]="nosniff"
        response.headers["Referrer-Policy"]="no-referrer"
        response.headers["Content-Security-Policy"]="default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' blob: data:; media-src 'self' blob:; connect-src 'self'; frame-ancestors 'none'"
        if request.url.path=='/' or request.url.path.endswith(('.html','.js','.css')):
            response.headers['Cache-Control']='no-cache'
        return response

    def get_job(identity):
        job=manager.jobs.get(identity)
        if not job: raise HTTPException(404,"任务不存在")
        return job

    @app.get("/api/health")
    def health():
        return {"schema_version":1,"model_status":manager.model_status,"message":manager.model_message,
                "error":manager.model_error,"providers":manager.model.providers if manager.model else [],
                "model":"RTMO-s","version":"0.2.0","caption_model_status":manager.caption_model_status}

    @app.get("/api/jobs")
    def jobs():
        return {"jobs": sorted([j.snapshot() for j in list(manager.jobs.values())],key=lambda j:-j["created_at"])[:50]}

    @app.get("/api/catalogs")
    def catalogs(): return {"catalogs":CATALOGS}

    @app.post("/api/jobs",status_code=201)
    async def upload(file:UploadFile=File(...),mode:str=Form("stream"),source_url:str=Form(""),analysis_fps:int=Form(10),tracker:str=Form("ocsort"),group_id:str=Form("auto")):
        if mode not in ("stream","complete") or analysis_fps not in (10,15,30) or tracker not in ("ocsort","bytetrack","cbiou"):
            raise HTTPException(422,"无效的分析选项")
        if group_id not in {"auto","none",*(c["id"] for c in CATALOGS)}:
            raise HTTPException(422,"成员名单不存在")
        if len(source_url)>2000 or (source_url and (urlparse(source_url).scheme not in ("https","http") or not urlparse(source_url).netloc)):
            raise HTTPException(422,"来源需要是有效的 HTTP 或 HTTPS 链接")
        filename=Path((file.filename or "video.mp4").replace("\\","/")).name[:200]
        extension=Path(filename).suffix.lower()
        if extension not in (".mp4",".mov",".mkv",".webm",".m4v"):
            raise HTTPException(422,"请上传 MP4、MOV、MKV 或 WebM 视频")
        directory=manager.allocate(); path=directory/("video"+extension)
        try:
            size=0
            with path.open("wb") as out:
                while chunk:=await file.read(1024*1024):
                    size+=len(chunk)
                    if size>MAX_UPLOAD: raise HTTPException(413,"第一版支持最大 2GB 的视频")
                    out.write(chunk)
            info=await run_in_threadpool(inspect_video,path)
            job=manager.create(path,filename,info,mode,source_url,analysis_fps,tracker,group_id)
            return job.snapshot()
        except HTTPException:
            shutil.rmtree(directory); raise
        except Exception as exc:
            shutil.rmtree(directory)
            raise HTTPException(422,f"无法读取视频：{exc}") from exc
        finally:
            await file.close()

    @app.delete("/api/jobs/{identity}", status_code=204)
    def delete_job(identity:str):
        if not manager.delete(identity): raise HTTPException(404,"任务不存在")
        return Response(status_code=204)

    @app.get("/api/jobs/{identity}")
    def status(identity:str): return get_job(identity).snapshot()

    @app.put("/api/jobs/{identity}/title")
    def retitle(identity:str, payload:JobTitle):
        job=get_job(identity)
        with job.lock:
            job.meta['title']=payload.title
        job.save()
        return job.snapshot()

    @app.get("/api/jobs/{identity}/frames")
    def frames(identity:str,after:int=0):
        if after<0: raise HTTPException(422,"无效游标")
        job=get_job(identity)
        with job.lock:
            batch=job.frames[after:after+300]
            return {"frames":batch,"next":after+len(batch),"total":len(job.frames),"job":job.snapshot()}

    @app.get("/api/jobs/{identity}/video")
    def video(identity:str):
        job=get_job(identity)
        return FileResponse(job.directory/job.meta["media_name"])

    @app.post("/api/jobs/{identity}/cancel")
    def cancel(identity:str):
        job=get_job(identity)
        if job.meta["status"] not in ("complete","failed","cancelled","interrupted"):
            job.cancel.set()
            with job.lock: job.meta["message"]="正在结束当前帧"
        return job.snapshot()

    @app.put("/api/jobs/{identity}/labels/{track_id}")
    def label(identity:str,track_id:str,payload:Label):
        job=get_job(identity)
        if track_id not in job.meta.get("track_ids",[]): raise HTTPException(404,"轨迹不存在")
        with job.lock:
            name=payload.name.strip()
            if name: job.meta["labels"][track_id]={"name":name,"evidence":"user_confirmed"}
            else: job.meta["labels"].pop(track_id,None)
            job.save()
        return job.snapshot()

    @app.get("/api/agent/requests")
    def requests():
        return {"schema_version":1,"requests":agent_requests(list(manager.jobs.values()))}

    @app.get('/api/jobs/{identity}/agent-context')
    def agent_context(identity:str):
        job=get_job(identity)
        with job.lock:
            return {'job':job.snapshot(),'tracks':[dict(row) for row in job.tracks.values()],
                    'review':review_scope(job),'frames_url':f'/api/jobs/{identity}/frames',
                    'video_url':f'/api/jobs/{identity}/video',
                    'evidence_rule':'名单与演唱字幕不证明画面身份。标注来源必须明确对应人物，禁止凭人脸猜名。'}

    @app.put('/api/jobs/{identity}/annotations')
    def annotations(identity:str,payload:AnnotationResult):
        job=get_job(identity)
        with job.lock:
            try: apply_annotations(job,payload)
            except AnnotationConflict as exc: raise HTTPException(409,str(exc)) from exc
            except ValueError as exc: raise HTTPException(422,str(exc)) from exc
            job.save()
        return job.snapshot()

    @app.put("/api/jobs/{identity}/roster")
    def roster(identity:str,payload:Roster):
        job=get_job(identity)
        for member in payload.members:
            if urlparse(member.source).scheme not in ("http","https"):
                raise HTTPException(422,"每位成员都需要一个资料来源链接")
        with job.lock:
            members=[m.model_dump() for m in payload.members]
            if members!=job.meta.get('roster',[]):
                if not job.meta.get('annotation_reviewed') and job.meta.get('annotation_status')!='pending':
                    job.meta['annotation_reviewed']=review_scope(job)
                job.meta['roster_revision']=job.meta.get('roster_revision',0)+1
                job.meta["roster"]=members
                refresh_caption_hints(job.meta)
            job.meta["source_task"]="complete"
            job.save()
        return job.snapshot()

    @app.get("/api/jobs/{identity}/statistics")
    def statistics(identity:str, until:float|None=None,appearance:bool=True,view:Literal['tracks','members']='tracks'):
        if until is not None and (not math.isfinite(until) or until<0):
            raise HTTPException(422,"统计时间必须是非负有限秒数")
        job=get_job(identity)
        with job.lock:
            result=center_statistics(job.frames,job.meta['labels'],job.meta.get('annotations',[]),until,job.meta.get('appearance_links') if appearance else None)
            return member_statistics(result) if view=='members' else result

    @app.get("/api/jobs/{identity}/export")
    def export(identity:str,format:str="json",until:float|None=None,appearance:bool=True,view:Literal['tracks','members']='tracks'):
        if until is not None and (not math.isfinite(until) or until<0):
            raise HTTPException(422,"统计时间必须是非负有限秒数")
        job=get_job(identity)
        with job.lock:
            ranking,unknown=totals(job.frames,until=until)
            people_ranking,unnamed=named_totals(job.frames,job.meta["labels"],annotations=job.meta.get('annotations',[]),until=until)
            statistics=center_statistics(job.frames,job.meta["labels"],job.meta.get("annotations",[]),until,job.meta.get('appearance_links') if appearance else None)
            if view=='members': statistics=member_statistics(statistics)
            if format=="csv":
                stream=io.StringIO(); writer=csv.writer(stream)
                writer.writerow(["name","center_seconds","equivalent_seconds","track_count","identity_status","key","until_seconds"])
                for row in statistics['rows']:
                    name=row["name"]
                    if name.startswith(("=","+","-","@")): name="'"+name
                    writer.writerow([name,round(row["seconds"],3),round(row["equivalent_seconds"],3),row["track_count"],
                                     'named' if row['named'] else 'tentative_garment_group' if row.get('association') else 'anonymous_track',row['key'],statistics['until']])
                if view=='members':
                    # Union of intervals with an unnamed center, not the sum of fragments.
                    writer.writerow(["未对应姓名的 C 位区间",round(statistics['unbound'],3),"",0,"unresolved_interval","",statistics['until']])
                writer.writerow(["未判定 C 位",round(statistics['unknown'],3),round(statistics['unknown'],3),0,"unknown","",statistics['until']])
                return Response("\ufeff"+stream.getvalue(),media_type="text/csv",headers={"Content-Disposition":'attachment; filename="centerstage.csv"'})
            if format!="json": raise HTTPException(422,"格式应为 json 或 csv")
            return JSONResponse({"schema_version":1,"statistics":statistics,"job":job.snapshot(),"ranking":ranking,"people_ranking":people_ranking,"unnamed_center":unnamed,"unknown_seconds":unknown,"frames":list(job.frames)},
                headers={"Content-Disposition":'attachment; filename="centerstage.json"'})


    # === 智能识别API ===
    @app.post("/api/jobs/{identity}/auto-identify")
    async def auto_identify_members_endpoint(identity: str):
        """Reject the retired roster-order naming path without changing job data."""
        job = get_job(identity)
        with job.lock:
            status = name_status(job.meta)
        return JSONResponse(status_code=409, content={
            "success": False,
            "code": "name_evidence_required",
            "message": "不能按出现频率、C 位时长或名单顺序分配真实姓名。请使用带明确人物来源标注的 annotations 接口。",
            "name_status": status,
            "context_url": f"/api/jobs/{identity}/agent-context",
        })


    # ============ 配置管理API ============

    @app.get("/api/config")
    async def get_config_api():
        """Only advertise options implemented by the active service."""
        return {'read_only': True, 'model': 'RTMO-s', 'inference_batch_size': 1,
                'providers': manager.model.providers if manager.model else [],
                'analysis_fps': [10, 15, 30], 'trackers': ['ocsort', 'bytetrack', 'cbiou'],
                'modes': ['stream', 'complete'], 'max_upload_bytes': MAX_UPLOAD,
                'scoring': 'visual-center-v5-face-count', 'configuration_scope': 'per_upload'}

    @app.post("/api/config")
    async def update_config_api(request: Request):
        raise HTTPException(409, '不支持运行中改写全局模型和评分配置；请在导入视频时选择已支持的分析选项')

    @app.get("/api/performance/stats")
    async def get_performance_stats():
        return {'model_status': manager.model_status, 'jobs': [
            {key: snapshot.get(key) for key in ('id', 'status', 'analysis_fps', 'elapsed', 'speed',
                                               'first_result_seconds', 'ready_seconds', 'confirmed_until')}
            for job in list(manager.jobs.values()) for snapshot in [job.snapshot()]]}

    static=Path(__file__).parent/"static"
    app.mount("/",StaticFiles(directory=static,html=True),name="web")

    return app
