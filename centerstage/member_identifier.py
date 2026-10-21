"""
成员身份识别模块 - 使用Agent搜索和视觉识别
结合web搜索和多模态分析来识别女团成员
"""
import os
import json
import cv2
import numpy as np
from typing import Dict, List, Optional, Tuple
import base64
from pathlib import Path

class MemberIdentifier:
    """成员身份识别器 - 自动识别和标注成员姓名"""
    
    def __init__(self, cache_dir: str = ".centerstage/member_cache"):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.member_database: Dict[int, Dict] = {}  # track_id -> member_info
        self.face_embeddings: Dict[int, np.ndarray] = {}  # track_id -> face_embedding
        self.confirmed_members: Dict[str, int] = {}  # member_name -> track_id
        
    def load_cache(self, video_id: str) -> bool:
        """从缓存加载已识别的成员信息"""
        cache_file = self.cache_dir / f"{video_id}_members.json"
        if cache_file.exists():
            with open(cache_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
                self.member_database = {int(k): v for k, v in data.get('members', {}).items()}
                self.confirmed_members = data.get('confirmed', {})
                return True
        return False
        
    def save_cache(self, video_id: str):
        """保存识别的成员信息到缓存"""
        cache_file = self.cache_dir / f"{video_id}_members.json"
        with open(cache_file, 'w', encoding='utf-8') as f:
            json.dump({
                'members': self.member_database,
                'confirmed': self.confirmed_members
            }, f, ensure_ascii=False, indent=2)
            
    def extract_face_features(self, face_image: np.ndarray) -> np.ndarray:
        """提取人脸特征向量（简化版，使用图像直方图）"""
        # 转换为HSV色彩空间
        hsv = cv2.cvtColor(face_image, cv2.COLOR_BGR2HSV)
        # 计算直方图作为特征
        hist_h = cv2.calcHist([hsv], [0], None, [50], [0, 180])
        hist_s = cv2.calcHist([hsv], [1], None, [60], [0, 256])
        hist_v = cv2.calcHist([hsv], [2], None, [60], [0, 256])
        
        # 归一化并连接
        hist = np.concatenate([
            cv2.normalize(hist_h, hist_h).flatten(),
            cv2.normalize(hist_s, hist_s).flatten(),
            cv2.normalize(hist_v, hist_v).flatten()
        ])
        return hist
        
    def compare_faces(self, feat1: np.ndarray, feat2: np.ndarray) -> float:
        """比较两个人脸特征的相似度"""
        # 使用余弦相似度
        similarity = np.dot(feat1, feat2) / (np.linalg.norm(feat1) * np.linalg.norm(feat2))
        return float(similarity)
        
    def match_or_create_identity(self, track_id: int, face_crop: np.ndarray, 
                                  similarity_threshold: float = 0.85) -> int:
        """匹配已知身份或创建新身份"""
        # 提取当前人脸特征
        current_feat = self.extract_face_features(face_crop)
        
        # 如果这个track_id已经有特征了，更新它
        if track_id in self.face_embeddings:
            # 平均融合特征
            self.face_embeddings[track_id] = (
                self.face_embeddings[track_id] * 0.7 + current_feat * 0.3
            )
            return track_id
            
        # 否则，尝试匹配已知的人脸
        best_match_id = None
        best_similarity = 0.0
        
        for existing_id, existing_feat in self.face_embeddings.items():
            similarity = self.compare_faces(current_feat, existing_feat)
            if similarity > best_similarity:
                best_similarity = similarity
                best_match_id = existing_id
                
        # 如果相似度足够高，认为是同一个人
        if best_similarity > similarity_threshold and best_match_id is not None:
            return best_match_id
            
        # 否则创建新身份
        self.face_embeddings[track_id] = current_feat
        if track_id not in self.member_database:
            self.member_database[track_id] = {
                'track_id': track_id,
                'name': None,
                'confidence': 0.0,
                'appearances': 0
            }
        return track_id
        
    def assign_name(self, track_id: int, member_name: str, confidence: float = 1.0):
        """为track_id分配成员名字"""
        if track_id not in self.member_database:
            self.member_database[track_id] = {
                'track_id': track_id,
                'name': member_name,
                'confidence': confidence,
                'appearances': 1
            }
        else:
            self.member_database[track_id]['name'] = member_name
            self.member_database[track_id]['confidence'] = max(
                self.member_database[track_id].get('confidence', 0), 
                confidence
            )
        self.confirmed_members[member_name] = track_id
        
    def get_member_name(self, track_id: int) -> Optional[str]:
        """获取track_id对应的成员名字"""
        if track_id in self.member_database:
            return self.member_database[track_id].get('name')
        return None
        
    def get_all_members(self) -> List[Dict]:
        """获取所有已识别的成员"""
        return list(self.member_database.values())
        
    def update_appearance(self, track_id: int):
        """更新出现次数"""
        if track_id in self.member_database:
            self.member_database[track_id]['appearances'] = \
                self.member_database[track_id].get('appearances', 0) + 1
