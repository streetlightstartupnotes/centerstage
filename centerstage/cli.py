import argparse
import json
import sys
import time
from pathlib import Path


def main():
    parser=argparse.ArgumentParser(description="Centerstage · 本地女团 C 位分析")
    parser.add_argument("--url",default="http://127.0.0.1:8640")
    sub=parser.add_subparsers(dest="command",required=True)
    serve=sub.add_parser("serve",help="启动本地网页和分析引擎")
    serve.add_argument("--port",type=int,default=8640)
    sub.add_parser("doctor",help="检查环境和已缓存模型")
    prepare=sub.add_parser("prepare",help="下载并预热 C 位模型")
    prepare.add_argument("--with-ocr",action="store_true",help="额外预热可选文字模型")
    analyze=sub.add_parser("analyze",help="把本地视频交给正在运行的服务")
    analyze.add_argument("video",type=Path)
    analyze.add_argument("--wait",action="store_true")
    analyze.add_argument("--source",default="")
    analyze.add_argument("--fps",type=int,choices=[10,15,30],default=10)
    analyze.add_argument("--tracker",choices=["ocsort","bytetrack","cbiou"],default="ocsort")
    for action in ("status","cancel","export"):
        item=sub.add_parser(action);item.add_argument("job_id")
        if action=="export":item.add_argument("--output",required=True,type=Path)
    sub.add_parser("jobs")
    sub.add_parser("requests",help="获取需要 Agent 查询的来源名单任务")
    roster=sub.add_parser("resolve-roster")
    roster.add_argument("job_id");roster.add_argument("--file",required=True,type=Path)
    context=sub.add_parser('agent-context');context.add_argument('job_id')
    annotation=sub.add_parser('resolve-annotations');annotation.add_argument('job_id');annotation.add_argument('--file',required=True,type=Path)
    worker=sub.add_parser('agent-worker',help='用本地 Agent JSON 适配器持续处理搜索标注任务')
    worker.add_argument('--once',action='store_true');worker.add_argument('--job')
    worker.add_argument('adapter',nargs=argparse.REMAINDER)
    label=sub.add_parser("label")
    label.add_argument("job_id");label.add_argument("track_id");label.add_argument("name")
    args=parser.parse_args()
    if args.command=='agent-worker':
        from .agent_worker import work
        command=args.adapter[1:] if args.adapter[:1]==['--'] else args.adapter
        try:work(args.url,command,args.once,args.job)
        except KeyboardInterrupt:pass
        return
    if args.command=="serve":
        import uvicorn
        uvicorn.run("centerstage.app:create_app",factory=True,host="127.0.0.1",port=args.port)
        return
    if args.command=="doctor":
        import platform, shutil, onnxruntime as ort
        from .config import DATA
        print(json.dumps({"python":platform.python_version(),"platform":platform.platform(),"providers":ort.get_available_providers(),
              "model_cached":(DATA/"models/rtmo-s.onnx").exists(),"ffmpeg":bool(shutil.which("ffmpeg")),"data_directory":str(DATA)},ensure_ascii=False))
        return
    if args.command=="prepare":
        from .config import DATA
        import os
        from .model import prepare_model, load_model
        model=load_model(prepare_model(DATA/"models",lambda s:print(s,file=sys.stderr)),os.environ.get("CENTERSTAGE_PROVIDER","auto"))
        from .captions import prepare_caption_reader
        ocr_ready=False
        if args.with_ocr and os.environ.get('CENTERSTAGE_OCR','1')!='0':
            try:ocr_ready=prepare_caption_reader(DATA/'models/ocr') is not None
            except Exception:print('可选字幕模型准备失败，C 位分析不受影响',file=sys.stderr)
        print(json.dumps({"ready":True,"providers":model.providers,"ocr_ready":ocr_ready}))
        return
    import httpx
    try:
        with httpx.Client(base_url=args.url,timeout=120) as client:
            if args.command=="analyze":
                with args.video.open("rb") as f:
                    response=client.post("/api/jobs",files={"file":(args.video.name,f,"application/octet-stream")},
                        data={"source_url":args.source,"analysis_fps":args.fps,"tracker":args.tracker})
                response.raise_for_status(); data=response.json(); print(json.dumps(data,ensure_ascii=False),flush=True)
                if args.wait:
                    while data["status"] not in ("complete","failed","cancelled","interrupted"):
                        time.sleep(1)
                        response=client.get("/api/jobs/"+data["id"]);response.raise_for_status();data=response.json()
                        print(json.dumps({k:data.get(k) for k in ("id","status","confirmed_until","elapsed","speed","message")},ensure_ascii=False),flush=True)
                    if data["status"]!="complete":sys.exit(1)
                return
            if args.command=="jobs": response=client.get("/api/jobs")
            elif args.command=="requests": response=client.get("/api/agent/requests")
            elif args.command=="status": response=client.get(f"/api/jobs/{args.job_id}")
            elif args.command=="cancel": response=client.post(f"/api/jobs/{args.job_id}/cancel")
            elif args.command=="label": response=client.put(f"/api/jobs/{args.job_id}/labels/{args.track_id}",json={"name":args.name})
            elif args.command=="resolve-roster": response=client.put(f"/api/jobs/{args.job_id}/roster",json=json.loads(args.file.read_text(encoding='utf-8')))
            elif args.command=='agent-context': response=client.get(f'/api/jobs/{args.job_id}/agent-context')
            elif args.command=='resolve-annotations': response=client.put(f'/api/jobs/{args.job_id}/annotations',json=json.loads(args.file.read_text(encoding='utf-8')))
            elif args.command=="export":
                response=client.get(f"/api/jobs/{args.job_id}/export")
                response.raise_for_status(); args.output.write_bytes(response.content)
                print(json.dumps({"saved":str(args.output.resolve())}));return
            response.raise_for_status();print(json.dumps(response.json(),ensure_ascii=False))
    except (httpx.HTTPError,OSError,ValueError) as exc:
        print(json.dumps({"error":str(exc)},ensure_ascii=False),file=sys.stderr);sys.exit(1)


if __name__=="__main__": main()
