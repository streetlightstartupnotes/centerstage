"""
智能识别API端点 - 集成到FastAPI应用
"""
from fastapi import APIRouter, HTTPException
from pathlib import Path
from .智能识别引擎 import SmartIdentifier
from .智能识别集成 import auto_identify_members, apply_names_to_frames

router = APIRouter()

def add_smart_identification_routes(app, manager):
    """添加智能识别相关的API路由"""
    
    @app.post("/api/jobs/{identity}/auto-identify")
    async def auto_identify(identity: str):
        """
        自动识别成员并标注姓名
        
        流程：
        1. 从视频标题/来源识别女团
        2. 获取成员名单（已知女团或Agent查询）
        3. 统计track出现频率
        4. 自动匹配姓名
        5. 应用到所有frame
        """
        job = manager.jobs.get(identity)
        if not job:
            raise HTTPException(404, "任务不存在")
        
        raise HTTPException(409, '旧版按名单顺序分配姓名的功能已停用；使用带明确人物来源依据的 annotations 接口。')

    @app.get("/api/jobs/{identity}/members")
    async def get_members(identity: str):
        """
        获取任务的成员信息（带姓名和统计）
        """
        job = manager.jobs.get(identity)
        if not job:
            raise HTTPException(404, "任务不存在")
        
        # 尝试加载识别结果
        identifier = SmartIdentifier(Path(manager.data) / "smart_ids")
        identifier.load(job.meta['id'])
        
        # 统计每个track的信息
        track_stats = {}
        for track_id, track_data in job.tracks.items():
            appearances = 0
            center_frames = 0
            
            for frame in job.frames:
                # 统计出现次数
                for person in frame.get('people', []):
                    if person['id'] == track_id:
                        appearances += 1
                        break
                
                # 统计C位次数
                if track_id in frame.get('centers', []):
                    center_frames += 1
            
            member_name = identifier.get_member_name(track_id)
            track_stats[track_id] = {
                'track_id': track_id,
                'name': member_name or track_id,
                'appearances': appearances,
                'center_frames': center_frames,
                'start': track_data.get('start', 0),
                'end': track_data.get('end', 0)
            }
        
        return {
            "roster": identifier.roster,
            "members": list(track_stats.values()),
            "total_tracks": len(track_stats)
        }
    
    @app.post("/api/jobs/{identity}/manual-label")
    async def manual_label(identity: str, track_id: str, member_name: str):
        """
        手动标注某个track的成员名字（兜底方案）
        """
        job = manager.jobs.get(identity)
        if not job:
            raise HTTPException(404, "任务不存在")
        
        # 加载识别器
        identifier = SmartIdentifier(Path(manager.data) / "smart_ids")
        identifier.load(job.meta['id'])
        
        # 手动修正
        identifier.manual_correction(track_id, member_name)
        
        # 保存
        identifier.save(job.meta['id'])
        
        # 更新job
        if 'member_names' not in job.meta:
            job.meta['member_names'] = {}
        job.meta['member_names'][track_id] = member_name
        job.save()
        
        return {
            "success": True,
            "track_id": track_id,
            "member_name": member_name,
            "message": "标注成功"
        }

    return app
