"""
自动成员命名模块
结合视觉特征和Agent搜索自动识别成员姓名
"""
import json
from pathlib import Path
from typing import Dict, List, Optional
import numpy as np

class AutoNamer:
    """
    自动命名器 - 为追踪的成员自动分配真实姓名
    
    策略：
    1. 提取每个track的视觉特征（服装、位置模式）
    2. 按出现频率和稳定性排序
    3. Agent查询女团成员名单
    4. 自动匹配和分配姓名
    """
    
    def __init__(self, cache_dir: Path):
        self.cache_dir = cache_dir
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.track_features: Dict[str, Dict] = {}  # track_id -> features
        self.name_mapping: Dict[str, str] = {}  # track_id -> member_name
        self.member_roster: List[str] = []  # 成员名单
        
    def update_track(self, track_id: str, appearance_data: Dict):
        """更新track的出现信息"""
        if track_id not in self.track_features:
            self.track_features[track_id] = {
                'appearances': 0,
                'total_center_time': 0.0,
                'positions': [],
                'garments': []
            }
        
        feat = self.track_features[track_id]
        feat['appearances'] += 1
        
        if 'garment' in appearance_data and appearance_data['garment']:
            feat['garments'].append(appearance_data['garment'])
            
        if 'box' in appearance_data:
            feat['positions'].append(appearance_data['box'])
            
    def set_roster(self, member_names: List[str]):
        """设置成员名单（从Agent查询获得）"""
        self.member_roster = member_names
        
    def auto_assign_names(self):
        """Retired: appearance frequency does not establish a real name."""
        raise ValueError('不能按轨迹出现次数和名单顺序分配真实姓名。')

    def get_name(self, track_id: str) -> Optional[str]:
        """获取track的成员名字"""
        return self.name_mapping.get(track_id)
        
    def get_all_mappings(self) -> Dict[str, str]:
        """获取所有映射"""
        return dict(self.name_mapping)
        
    def save(self, job_id: str):
        """保存命名结果"""
        cache_file = self.cache_dir / f"{job_id}_names.json"
        data = {
            'roster': self.member_roster,
            'mappings': self.name_mapping,
            'features': {k: {'appearances': v['appearances']} 
                        for k, v in self.track_features.items()}
        }
        cache_file.write_text(json.dumps(data, ensure_ascii=False, indent=2))
        
    def load(self, job_id: str) -> bool:
        """加载命名结果"""
        cache_file = self.cache_dir / f"{job_id}_names.json"
        if cache_file.exists():
            data = json.load(cache_file.open())
            self.member_roster = data.get('roster', [])
            self.name_mapping = {}  # Old unproven cache is retained on disk only.
            return False
        return False
