"""
C位检测器
基于位置、大小和清晰度综合判定C位
"""
import numpy as np
from typing import Dict, Tuple, Optional

class CenterPositionDetector:
    """C位检测器"""
    
    def __init__(self, 
                 distance_weight: float = 0.5,
                 size_weight: float = 0.3,
                 clarity_weight: float = 0.2):
        self.distance_weight = distance_weight
        self.size_weight = size_weight
        self.clarity_weight = clarity_weight
        
    def detect_center_person(self, 
                            identity_positions: Dict[int, Tuple],
                            frame_shape: Tuple[int, int, int]) -> Optional[int]:
        """
        检测C位人物
        
        Args:
            identity_positions: {identity_id: (bbox, confidence)}
            frame_shape: (height, width, channels)
            
        Returns:
            identity_id of center person, or None
        """
        if not identity_positions:
            return None
            
        frame_height, frame_width = frame_shape[:2]
        frame_center_x = frame_width / 2
        frame_center_y = frame_height / 2
        
        best_score = -1
        best_identity = None
        
        for identity_id, (bbox, conf) in identity_positions.items():
            # bbox: [x1, y1, x2, y2]
            x1, y1, x2, y2 = bbox[:4]
            
            # 计算人物中心点
            person_center_x = (x1 + x2) / 2
            person_center_y = (y1 + y2) / 2
            
            # 1. 距离得分 (越接近画面中心越高)
            distance = np.sqrt(
                (person_center_x - frame_center_x) ** 2 + 
                (person_center_y - frame_center_y) ** 2
            )
            max_distance = np.sqrt(frame_width**2 + frame_height**2) / 2
            distance_score = 1.0 - (distance / max_distance)
            
            # 2. 大小得分 (面部区域越大越高)
            bbox_area = (x2 - x1) * (y2 - y1)
            frame_area = frame_width * frame_height
            size_ratio = bbox_area / frame_area
            size_score = min(size_ratio * 10, 1.0)  # 归一化
            
            # 3. 清晰度得分 (使用置信度作为代理)
            clarity_score = conf
            
            # 综合得分
            total_score = (
                distance_score * self.distance_weight +
                size_score * self.size_weight +
                clarity_score * self.clarity_weight
            )
            
            if total_score > best_score:
                best_score = total_score
                best_identity = identity_id
                
        return best_identity
