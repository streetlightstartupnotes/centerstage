"""
视频处理器 V2 - 集成自动成员识别
"""
import cv2
import numpy as np
from ultralytics import YOLO
from deep_sort_realtime.deepsort_tracker import DeepSort
from typing import Dict, List, Tuple, Optional
import time
from .agent_identifier import AgentDrivenIdentifier
from .center_detector import CenterPositionDetector
import hashlib

class VideoProcessorV2:
    """视频处理器 - 支持自动成员识别和C位追踪"""
    
    def __init__(self, model_path: str = "yolov8n.pt"):
        # YOLO检测器
        self.yolo = YOLO(model_path)
        
        # DeepSORT追踪器
        self.tracker = DeepSort(
            max_age=30,
            n_init=3,
            nms_max_overlap=1.0,
            max_cosine_distance=0.3
        )
        
        # Agent驱动的成员识别器
        self.identifier = AgentDrivenIdentifier()
        
        # C位检测器
        self.center_detector = CenterPositionDetector()
        
        # 统计数据
        self.center_time_stats: Dict[int, float] = {}  # identity_id -> 累计C位时间
        self.current_center: Optional[int] = None
        self.frame_count = 0
        
    def process_frame(self, frame: np.ndarray, frame_idx: int, fps: float) -> Dict:
        """
        处理单帧
        返回：{
            'detections': [...],  # 检测结果
            'center_person': identity_id,  # 当前C位
            'stats': {...}  # 统计信息
        }
        """
        self.frame_count = frame_idx
        
        # 1. YOLO检测人物
        results = self.yolo(frame, classes=[0], verbose=False)  # class 0 = person
        
        if len(results) == 0 or len(results[0].boxes) == 0:
            return {
                'detections': [],
                'center_person': None,
                'stats': self._get_stats()
            }
            
        # 2. 准备DeepSORT输入
        boxes = results[0].boxes
        detections = []
        for box in boxes:
            x1, y1, x2, y2 = box.xyxy[0].cpu().numpy()
            conf = float(box.conf[0])
            detections.append(([x1, y1, x2 - x1, y2 - y1], conf, 'person'))
            
        # 3. DeepSORT追踪
        tracks = self.tracker.update_tracks(detections, frame=frame)
        
        # 4. 处理追踪结果并识别身份
        tracked_detections = []
        identity_positions = {}  # identity_id -> (bbox, conf)
        
        for track in tracks:
            if not track.is_confirmed():
                continue
                
            track_id = track.track_id
            ltrb = track.to_ltrb()
            
            # 使用Agent识别器统一身份
            identity_id = self.identifier.process_detection(
                track_id, ltrb, frame
            )
            
            # 获取成员名字
            member_name = self.identifier.get_member_name(identity_id)
            
            detection_info = {
                'track_id': track_id,
                'identity_id': identity_id,
                'bbox': ltrb.tolist(),
                'name': member_name,
                'confidence': 0.9
            }
            tracked_detections.append(detection_info)
            identity_positions[identity_id] = (ltrb, 0.9)
            
        # 5. 每隔一定帧数自动分配名字
        if frame_idx % 30 == 0:  # 每30帧（1秒）
            self.identifier.auto_assign_names()
            
        # 6. 检测C位
        if identity_positions:
            center_id = self.center_detector.detect_center_person(
                identity_positions, 
                frame.shape
            )
            
            # 更新C位统计
            if center_id is not None:
                time_increment = 1.0 / fps
                self.center_time_stats[center_id] = \
                    self.center_time_stats.get(center_id, 0.0) + time_increment
                self.current_center = center_id
        else:
            center_id = None
            self.current_center = None
            
        return {
            'detections': tracked_detections,
            'center_person': center_id,
            'stats': self._get_stats()
        }
        
    def _get_stats(self) -> Dict:
        """获取统计信息"""
        # 按C位时间排序
        sorted_stats = sorted(
            self.center_time_stats.items(),
            key=lambda x: x[1],
            reverse=True
        )
        
        stats_list = []
        for identity_id, total_time in sorted_stats:
            identity_info = self.identifier.get_identity_info(identity_id)
            stats_list.append({
                'identity_id': identity_id,
                'name': identity_info.get('name') if identity_info else None,
                'center_time': round(total_time, 2),
                'appearances': identity_info.get('appearances', 0) if identity_info else 0
            })
            
        return {
            'current_center': self.current_center,
            'current_center_name': self.identifier.get_member_name(self.current_center) if self.current_center else None,
            'members': stats_list,
            'total_members': len(self.identifier.identities)
        }
        
    def get_video_hash(self, video_path: str) -> str:
        """计算视频hash用于缓存"""
        return hashlib.md5(video_path.encode()).hexdigest()[:16]
        
    def save_results(self, video_path: str):
        """保存识别结果"""
        video_hash = self.get_video_hash(video_path)
        self.identifier.save_cache(video_hash)
        
    def load_results(self, video_path: str) -> bool:
        """加载缓存的识别结果"""
        video_hash = self.get_video_hash(video_path)
        return self.identifier.load_cache(video_hash)
