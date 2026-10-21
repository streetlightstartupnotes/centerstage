"""
人脸识别和成员匹配模块
使用DeepFace进行人脸识别和特征提取
"""
import os
import pickle
from typing import Dict, List, Optional, Tuple
import numpy as np
from deepface import DeepFace
import cv2

class MemberRecognizer:
    def __init__(self, db_path: str = "member_faces_db"):
        self.db_path = db_path
        self.member_embeddings: Dict[str, List[np.ndarray]] = {}
        self.load_database()
        
    def load_database(self):
        """加载已保存的成员人脸特征数据库"""
        db_file = os.path.join(self.db_path, "embeddings.pkl")
        if os.path.exists(db_file):
            with open(db_file, 'rb') as f:
                self.member_embeddings = pickle.load(f)
                
    def save_database(self):
        """保存成员人脸特征数据库"""
        os.makedirs(self.db_path, exist_ok=True)
        db_file = os.path.join(self.db_path, "embeddings.pkl")
        with open(db_file, 'wb') as f:
            pickle.dump(self.member_embeddings, f)
            
    def add_member_face(self, member_name: str, face_image: np.ndarray):
        """添加成员的人脸样本"""
        try:
            # 使用DeepFace提取人脸特征
            embedding = DeepFace.represent(
                face_image,
                model_name="Facenet512",
                enforce_detection=False
            )[0]["embedding"]
            
            if member_name not in self.member_embeddings:
                self.member_embeddings[member_name] = []
            self.member_embeddings[member_name].append(np.array(embedding))
            
            return True
        except Exception as e:
            print(f"提取人脸特征失败: {e}")
            return False
            
    def recognize_face(self, face_image: np.ndarray, threshold: float = 0.6) -> Optional[str]:
        """识别人脸，返回最匹配的成员名字"""
        if not self.member_embeddings:
            return None
            
        try:
            # 提取当前人脸特征
            embedding = DeepFace.represent(
                face_image,
                model_name="Facenet512",
                enforce_detection=False
            )[0]["embedding"]
            embedding = np.array(embedding)
            
            # 计算与所有成员的相似度
            best_match = None
            best_distance = float('inf')
            
            for member_name, member_embs in self.member_embedings.items():
                for member_emb in member_embs:
                    # 计算余弦距离
                    distance = np.linalg.norm(embedding - member_emb)
                    if distance < best_distance:
                        best_distance = distance
                        best_match = member_name
                        
            # 如果距离小于阈值，认为匹配成功
            if best_distance < threshold:
                return best_match
            return None
            
        except Exception as e:
            print(f"识别人脸失败: {e}")
            return None
            
    def batch_recognize(self, faces: List[Tuple[int, np.ndarray]]) -> Dict[int, str]:
        """批量识别人脸"""
        results = {}
        for track_id, face_image in faces:
            member_name = self.recognize_face(face_image)
            if member_name:
                results[track_id] = member_name
        return results
