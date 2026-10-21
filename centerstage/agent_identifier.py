"""
Agent驱动的成员识别服务
结合视觉分析和web搜索自动识别女团成员
"""
import os
import json
import cv2
import numpy as np
from pathlib import Path
from typing import Dict, List, Optional, Tuple
import hashlib

# A2O LITE 成员名单（从搜索结果获取）
A2O_LITE_MEMBERS = [
    "YOUNG", "HIMEKI", "VORA", "XILI", "RADA", 
    "MERCI", "AYUNE", "OA", "AIJING"
]

class AgentDrivenIdentifier:
    """Agent驱动的成员自动识别系统"""
    
    def __init__(self, cache_dir: str = ".centerstage/identities"):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        
        # track_id -> 成员信息
        self.identities: Dict[int, Dict] = {}
        
        # 人脸特征库：track_id -> 特征向量列表
        self.face_features: Dict[int, List[np.ndarray]] = {}
        
        # 成员名 -> track_id 的确认映射
        self.name_mapping: Dict[str, int] = {}
        
        # 可用成员列表
        self.available_members = A2O_LITE_MEMBERS.copy()
        
    def _extract_face_feature(self, face_crop: np.ndarray) -> np.ndarray:
        """提取人脸特征（使用颜色直方图+LBP）"""
        # 调整大小
        face_resized = cv2.resize(face_crop, (128, 128))
        
        # HSV颜色直方图
        hsv = cv2.cvtColor(face_resized, cv2.COLOR_BGR2HSV)
        hist_h = cv2.calcHist([hsv], [0], None, [30], [0, 180])
        hist_s = cv2.calcHist([hsv], [1], None, [32], [0, 256])
        hist_v = cv2.calcHist([hsv], [2], None, [32], [0, 256])
        
        # 归一化并拼接
        feature = np.concatenate([
            cv2.normalize(hist_h, hist_h).flatten(),
            cv2.normalize(hist_s, hist_s).flatten(),
            cv2.normalize(hist_v, hist_v).flatten()
        ])
        
        return feature
        
    def _compute_similarity(self, feat1: np.ndarray, feat2: np.ndarray) -> float:
        """计算特征相似度"""
        return float(np.dot(feat1, feat2) / (np.linalg.norm(feat1) * np.linalg.norm(feat2) + 1e-8))
        
    def process_detection(self, track_id: int, bbox: Tuple, frame: np.ndarray) -> int:
        """
        处理检测到的人脸，返回统一的identity_id
        如果是新人，创建新identity；如果匹配已知人脸，返回已知identity
        """
        x1, y1, x2, y2 = map(int, bbox[:4])
        face_crop = frame[y1:y2, x1:x2]
        
        if face_crop.size == 0:
            return track_id
            
        # 提取特征
        current_feature = self._extract_face_feature(face_crop)
        
        # 查找最匹配的identity
        best_match_id = None
        best_similarity = 0.0
        threshold = 0.75  # 相似度阈值
        
        for identity_id, features in self.face_features.items():
            # 与该identity的所有特征比较
            for feat in features:
                similarity = self._compute_similarity(current_feature, feat)
                if similarity > best_similarity:
                    best_similarity = similarity
                    best_match_id = identity_id
                    
        # 如果找到高相似度匹配，使用已有identity
        if best_similarity > threshold and best_match_id is not None:
            # 更新特征库（保留最近的5个特征）
            self.face_features[best_match_id].append(current_feature)
            if len(self.face_features[best_match_id]) > 5:
                self.face_features[best_match_id].pop(0)
            
            # 更新出现次数
            if best_match_id in self.identities:
                self.identities[best_match_id]['appearances'] += 1
                
            return best_match_id
            
        # 否则创建新identity
        if track_id not in self.face_features:
            self.face_features[track_id] = [current_feature]
            self.identities[track_id] = {
                'identity_id': track_id,
                'name': None,
                'confidence': 0.0,
                'appearances': 1,
                'first_seen_frame': -1
            }
        else:
            # 已存在的track_id，添加新特征
            self.face_features[track_id].append(current_feature)
            if len(self.face_features[track_id]) > 5:
                self.face_features[track_id].pop(0)
                
        return track_id
        
    def auto_assign_names(self):
        """Retired: track frequency cannot establish a real person's name."""
        raise ValueError('不能按轨迹出现次数和名单顺序分配真实姓名。')

    def get_member_name(self, identity_id: int) -> Optional[str]:
        """获取identity对应的成员名字"""
        if identity_id in self.identities:
            return self.identities[identity_id].get('name')
        return None
        
    def get_identity_info(self, identity_id: int) -> Optional[Dict]:
        """获取identity完整信息"""
        return self.identities.get(identity_id)
        
    def get_all_identities(self) -> List[Dict]:
        """获取所有identity信息"""
        return list(self.identities.values())
        
    def save_cache(self, video_hash: str):
        """保存识别结果"""
        cache_file = self.cache_dir / f"{video_hash}.json"
        data = {
            'identities': {str(k): v for k, v in self.identities.items()},
            'name_mapping': self.name_mapping
        }
        with open(cache_file, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            
    def load_cache(self, video_hash: str) -> bool:
        """加载缓存的识别结果"""
        cache_file = self.cache_dir / f"{video_hash}.json"
        if cache_file.exists():
            with open(cache_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
                self.identities = {int(k): v for k, v in data.get('identities', {}).items()}
                self.name_mapping = {}
                for item in self.identities.values():
                    item['name'] = None
                    item['confidence'] = 0.0
                return True
        return False
