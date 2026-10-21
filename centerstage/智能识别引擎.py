"""
Legacy roster/track diagnostics. Statistics are not real-name identity evidence.
Automatic roster-order assignment is retired; use the annotations API.
"""
import json
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple
import asyncio

class SmartIdentifier:
    """
    Compatibility container for source rosters and explicit user corrections.
    Frequency, center time and visible size cannot establish a real name.
    """
    
    def __init__(self, cache_dir: Path):
        self.cache_dir = cache_dir
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.roster: List[str] = []  # 女团成员完整名单
        self.track_mappings: Dict[str, str] = {}  # track_id -> member_name
        self.confidence_scores: Dict[str, float] = {}  # track_id -> confidence
        self.feature_scores: Dict[str, Dict] = {}  # track_id -> feature dict
        self.evidence: Dict[str, str] = {}
        
    async def identify_group(self, video_title: str, video_source: str) -> Optional[List[str]]:
        """
        第一步：识别女团并获取成员名单
        使用Agent搜索或内置知识库
        """
        # 从标题和来源中提取女团关键词
        keywords = self._extract_keywords(video_title, video_source)
        
        # 已知女团快速匹配
        known_groups = {
            'A2O': ['YOUNG', 'HIMEKI', 'VORA', 'XILI', 'RADA', 'MERCI', 'AYUNE', 'OA', 'AIJING'],
            'BLACKPINK': ['JISOO', 'JENNIE', 'ROSÉ', 'LISA'],
            'TWICE': ['NAYEON', 'JEONGYEON', 'MOMO', 'SANA', 'JIHYO', 'MINA', 'DAHYUN', 'CHAEYOUNG', 'TZUYU'],
            'AESPA': ['KARINA', 'GISELLE', 'WINTER', 'NINGNING'],
            'IVE': ['YUJIN', 'GAEUL', 'REI', 'WONYOUNG', 'LIZ', 'LEESEO'],
            'NEWJEANS': ['MINJI', 'HANNI', 'DANIELLE', 'HAERIN', 'HYEIN'],
        }
        
        for group_name, members in known_groups.items():
            if group_name.upper() in keywords.upper():
                self.roster = members
                print(f"✓ 识别女团: {group_name} ({len(members)}名成员)")
                return members
        
        # 如果没有匹配到，返回None表示需要Agent查询
        return None
        
    def _extract_keywords(self, title: str, source: str) -> str:
        """提取关键词"""
        text = f"{title} {source}".upper()
        # 移除标点符号
        text = re.sub(r'[^ws]', ' ', text)
        return text
        
    def calculate_track_features(self, track_stats: Dict[str, Dict]) -> Dict[str, Dict]:
        """
        计算每个track的多维度特征
        
        特征包括：
        - appearances: 出现帧数
        - center_time: C位时长
        - avg_size: 平均人物大小
        - center_score: 画面中心度
        - continuity: 时序连续性
        """
        features = {}
        
        # 计算总出现次数用于归一化
        max_appearances = max((s.get('appearances', 0) for s in track_stats.values()), default=1)
        max_center_time = max((s.get('center_time', 0) for s in track_stats.values()), default=1)
        max_size = max((s.get('avg_size', 0) for s in track_stats.values()), default=1)
        max_center_score = max((s.get('center_score', 0) for s in track_stats.values()), default=1)
        
        for track_id, stats in track_stats.items():
            # 归一化各项特征
            norm_appearances = stats.get('appearances', 0) / max_appearances if max_appearances > 0 else 0
            norm_center_time = stats.get('center_time', 0) / max_center_time if max_center_time > 0 else 0
            norm_size = stats.get('avg_size', 0) / max_size if max_size > 0 else 0
            norm_center_score = stats.get('center_score', 0) / max_center_score if max_center_score > 0 else 0
            
            # 综合评分（加权）
            # 出现频率40% + C位时长30% + 中心度20% + 大小10%
            composite_score = (
                norm_appearances * 0.4 +
                norm_center_time * 0.3 +
                norm_center_score * 0.2 +
                norm_size * 0.1
            )
            
            features[track_id] = {
                'appearances': stats.get('appearances', 0),
                'center_time': stats.get('center_time', 0),
                'avg_size': stats.get('avg_size', 0),
                'center_score': stats.get('center_score', 0),
                'composite_score': composite_score,
                'track_count': stats.get('track_count', 1)
            }
        
        self.feature_scores = features
        return features
        
    def auto_match_tracks(self, track_stats: Dict[str, Dict]) -> Dict[str, str]:
        """A roster and salience statistics do not identify visible people."""
        raise ValueError('不能按出现频率、C 位时长或名单顺序分配真实姓名；需要明确人物来源标注。')
    
    def get_member_name(self, track_id: str) -> Optional[str]:
        """获取track对应的成员名字"""
        return self.track_mappings.get(track_id)
        
    def get_all_mappings(self) -> Dict[str, Dict]:
        """获取所有映射（包含置信度和特征）"""
        return {
            track_id: {
                'name': name,
                'confidence': self.confidence_scores.get(track_id, 0.5),
                'features': self.feature_scores.get(track_id, {})
            }
            for track_id, name in self.track_mappings.items()
        }
    
    def manual_correction(self, track_id: str, member_name: str):
        """手动修正（兜底方案）"""
        self.track_mappings[track_id] = member_name
        self.confidence_scores[track_id] = 1.0  # 手动标注置信度最高
        self.evidence[track_id] = 'user_confirmed'
        
    def save(self, job_id: str):
        """保存识别结果"""
        cache_file = self.cache_dir / f"{job_id}_smart_id.json"
        data = {
            'schema_version': 2,
            'evidence': self.evidence,
            'roster': self.roster,
            'mappings': self.track_mappings,
            'confidence': self.confidence_scores,
            'features': self.feature_scores
        }
        cache_file.write_text(json.dumps(data, ensure_ascii=False, indent=2))
        
    def load(self, job_id: str) -> bool:
        """加载识别结果"""
        cache_file = self.cache_dir / f"{job_id}_smart_id.json"
        if cache_file.exists():
            data = json.load(cache_file.open())
            self.roster = data.get('roster', [])
            self.track_mappings = {}
            self.confidence_scores = {}
            self.evidence = {}
            if data.get('schema_version') != 2:
                return False  # Preserve old cache on disk, but never trust guessed names.
            self.track_mappings = {key: value for key, value in data.get('mappings', {}).items()
                                   if data.get('evidence', {}).get(key) == 'user_confirmed'}
            self.evidence = {key: 'user_confirmed' for key in self.track_mappings}
            self.confidence_scores = {key: 1.0 for key in self.track_mappings}
            self.feature_scores = data.get('features', {})
            return True
        return False

