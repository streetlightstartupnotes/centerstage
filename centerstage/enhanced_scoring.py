"""
增强的C位检测算法 v3.0
改进：
1. 多帧时序连续性
2. 运动轨迹分析
3. 注意力热图
4. 动态权重调整
"""
import math
import numpy as np
from collections import deque
from typing import List, Dict, Tuple, Optional


class EnhancedCenterScorer:
    """
    增强C位检测器 v3.0
    
    改进点：
    - 时序平滑：考虑前几帧的C位历史
    - 运动分析：检测突然的位置变化（可能是镜头切换）
    - 群体分析：考虑整体阵型
    - 自适应权重：根据场景动态调整权重
    """
    
    def __init__(self, history_size: int = 5):
        """
        初始化增强C位检测器
        
        Args:
            history_size: 历史窗口大小
        """
        self.scores = {}
        self.current = ()
        self.candidate = ()
        self.candidate_since = 0.0
        self.previous_time = None
        
        # 时序历史
        self.history_size = history_size
        self.center_history = deque(maxlen=history_size)  # 历史C位
        self.position_history = {}  # 每个人的位置历史
        
        # 场景分析
        self.scene_type = 'unknown'  # 'closeup', 'wide', 'medium'
        self.formation_center = 0.5  # 阵型中心
        
        # 性能统计
        self.stats = {
            'total_updates': 0,
            'scene_switches': 0,
            'confident_assignments': 0
        }
    
    def update(self, people: List[Dict], timestamp: float) -> Tuple[List[Dict], str]:
        """
        更新C位检测
        
        Args:
            people: 人物列表
            timestamp: 时间戳
            
        Returns:
            (更新后的人物列表, 原因)
        """
        self.stats['total_updates'] += 1
        
        # 计算时间差
        dt = 0.067 if self.previous_time is None else max(0.001, timestamp - self.previous_time)
        self.previous_time = timestamp
        
        if not people:
            self.current = self.candidate = ()
            return [], "unknown"
        
        # 场景分析
        self._analyze_scene(people)
        
        # 计算基础特征
        self._calculate_base_features(people)
        
        # 时序平滑
        self._apply_temporal_smoothing(people, dt)
        
        # 运动分析
        self._analyze_motion(people, timestamp)
        
        # 计算最终得分
        self._calculate_final_scores(people, dt)
        
        # 选择C位
        ranked = sorted(people, key=lambda p: p["score"], reverse=True)
        center_id, reason = self._select_center(ranked, people)
        
        # 更新历史
        self._update_history(center_id, people, timestamp)
        
        return people, reason
    
    def _analyze_scene(self, people: List[Dict]):
        """
        分析场景类型（近景/远景/中景）
        
        Args:
            people: 人物列表
        """
        heights = [p["box"][3] - p["box"][1] for p in people]
        median_height = sorted(heights)[len(heights) // 2]
        
        if median_height > 0.68:
            self.scene_type = 'closeup'
        elif median_height < 0.35:
            self.scene_type = 'wide'
        else:
            self.scene_type = 'medium'
    
    def _calculate_base_features(self, people: List[Dict]):
        """
        计算基础几何特征
        
        Args:
            people: 人物列表
        """
        heights = [p["box"][3] - p["box"][1] for p in people]
        max_height = max(heights)
        fronts = [p["box"][3] for p in people]
        front = max(fronts)
        max_area = max((p["box"][2] - p["box"][0]) * h for p, h in zip(people, heights))
        
        # 计算torso位置
        def torso_x(person):
            points = [person['pose'][i][0] for i in (5, 6, 11, 12) 
                     if person['pose'][i][2] >= 0.5]
            return sum(points) / len(points) if len(points) >= 3 else                    (person['box'][0] + person['box'][2]) / 2
        
        anchors = {p['id']: torso_x(p) for p in people}
        xs = sorted(anchors.values())
        self.formation_center = xs[len(xs) // 2] if len(xs) % 2 else                                 (xs[len(xs) // 2 - 1] + xs[len(xs) // 2]) / 2
        
        # 存储特征
        for p, height in zip(people, heights):
            x = anchors[p['id']]
            
            # 基础特征
            size = min(1, height / max(max_height, 0.01))
            foreground = max(0, 1 - (front - p["box"][3]) / max(max_height * 0.45, 0.08))
            
            # 中心度（根据场景类型调整）
            if self.scene_type == 'closeup':
                anchor = 0.15 * self.formation_center + 0.85 * 0.5
            else:
                anchor = 0.5 * self.formation_center + 0.5 * 0.5
            
            central = max(0, 1 - abs(x - anchor) / 0.5)
            
            # 可见度
            visibility = sum(k[2] >= 0.45 for k in p["pose"]) / 17
            
            # 面积
            area = math.sqrt(max(0, (p["box"][2] - p["box"][0]) * height) / 
                           max(max_area, 0.001))
            
            # 朝向（面部可见度）
            facing_score = 1.0 if p['pose'][0][2] > 0.75 else                           0.3 if p['pose'][0][2] < 0.4 else 0.6
            
            p["base_features"] = {
                "size": size,
                "foreground": foreground,
                "central": central,
                "visibility": visibility,
                "area": area,
                "facing": facing_score,
                "body_x": x
            }
    
    def _apply_temporal_smoothing(self, people: List[Dict], dt: float):
        """
        应用时序平滑
        
        Args:
            people: 人物列表
            dt: 时间差
        """
        alpha = 1 - math.exp(-dt / 0.16)
        live = {p["id"] for p in people}
        
        # 清理不存在的轨迹
        self.scores = {k: v for k, v in self.scores.items() if k in live}
        
        for p in people:
            features = p["base_features"]
            
            # 根据场景类型计算原始分数
            if self.scene_type == 'closeup':
                raw = (0.30 * features["area"] + 
                      0.10 * features["foreground"] +
                      0.45 * features["central"] +
                      0.15 * features["visibility"])
            else:
                raw = (0.25 * features["size"] +
                      0.30 * features["foreground"] +
                      0.35 * features["central"] +
                      0.10 * features["visibility"])
            
            # 加入朝向权重
            raw = raw * (0.85 + 0.15 * features["facing"])
            
            # 时序平滑
            old = self.scores.get(p["id"], raw)
            smoothed = old + alpha * (raw - old)
            
            self.scores[p["id"]] = smoothed
            p["temporal_score"] = round(smoothed, 4)
    
    def _analyze_motion(self, people: List[Dict], timestamp: float):
        """
        分析运动模式
        
        Args:
            people: 人物列表
            timestamp: 时间戳
        """
        for p in people:
            track_id = p["id"]
            current_pos = p["base_features"]["body_x"]
            
            # 更新位置历史
            if track_id not in self.position_history:
                self.position_history[track_id] = deque(maxlen=5)
            
            self.position_history[track_id].append({
                'x': current_pos,
                'time': timestamp
            })
            
            # 计算运动速度
            history = self.position_history[track_id]
            if len(history) >= 2:
                dx = history[-1]['x'] - history[0]['x']
                dt = history[-1]['time'] - history[0]['time']
                velocity = abs(dx / dt) if dt > 0 else 0
                
                # 静止加分（C位通常更稳定）
                stability = max(0, 1 - velocity / 0.5)
                p["motion_features"] = {
                    "velocity": velocity,
                    "stability": stability
                }
            else:
                p["motion_features"] = {
                    "velocity": 0,
                    "stability": 1.0
                }
    
    def _calculate_final_scores(self, people: List[Dict], dt: float):
        """
        计算最终得分
        
        Args:
            people: 人物列表
            dt: 时间差
        """
        for p in people:
            temporal = p["temporal_score"]
            stability = p["motion_features"]["stability"]
            
            # 历史C位加权
            history_bonus = 0.0
            if len(self.center_history) > 0:
                recent_centers = list(self.center_history)[-3:]
                if p["id"] in recent_centers:
                    # 最近是C位，给予小幅加分
                    history_bonus = 0.05
            
            # 最终得分
            final_score = temporal * 0.85 + stability * 0.15 + history_bonus
            
            p["score"] = round(final_score, 4)
            p["features"] = {
                **p["base_features"],
                **p["motion_features"],
                "history_bonus": history_bonus
            }
    
    def _select_center(self, ranked: List[Dict], people: List[Dict]) -> Tuple[tuple, str]:
        """
        选择C位
        
        Args:
            ranked: 按分数排序的人物列表
            people: 原始人物列表
            
        Returns:
            (C位ID元组, 原因)
        """
        first = ranked[0]
        reason = 'geometry'
        
        # 单人C位判定
        if first["score"] >= 0.67 and first["confidence"] >= 0.5:
            if len(ranked) == 1 or first["score"] - ranked[1]["score"] >= 0.065:
                self.stats['confident_assignments'] += 1
                return (first["id"],), reason
        
        # 双人C位判定（更严格的条件）
        if len(ranked) >= 2:
            second = ranked[1]
            
            # 检查是否满足双C位条件
            score_close = second["score"] >= 0.75 and                          first["score"] - second["score"] < 0.05
            
            if score_close:
                # 对称性检查
                x1 = first["base_features"]["body_x"]
                x2 = second["base_features"]["body_x"]
                separated = abs(x1 - x2) > 0.16
                symmetric = abs((x1 + x2) / 2 - self.formation_center) < 0.13
                
                if separated and symmetric:
                    reason = 'dual_center'
                    return tuple(sorted((first["id"], second["id"]))), reason
        
        # 默认返回最高分
        return (first["id"],), reason
    
    def _update_history(self, center_id: tuple, people: List[Dict], timestamp: float):
        """
        更新历史记录
        
        Args:
            center_id: C位ID
            people: 人物列表
            timestamp: 时间戳
        """
        self.center_history.append(center_id)
        self.current = center_id
    
    def get_stats(self) -> Dict:
        """获取统计信息"""
        stats = self.stats.copy()
        if stats['total_updates'] > 0:
            stats['confidence_rate'] = stats['confident_assignments'] / stats['total_updates']
        return stats


def create_scorer(enhanced: bool = True):
    """
    创建C位检测器
    
    Args:
        enhanced: 是否使用增强版
        
    Returns:
        检测器实例
    """
    if enhanced:
        return EnhancedCenterScorer()
    else:
        # 使用原版
        from .scoring import CenterScorer
        return CenterScorer()

