"""
CenterStage 配置管理系统 v2.0
整合原有config.py和新的ConfigManager，支持环境变量、文件和运行时配置
"""
import os
from pathlib import Path
from typing import Optional
from dataclasses import dataclass, field

# ============ 原有配置常量（保持兼容） ============
DATA = Path(os.environ.get("CENTERSTAGE_DATA", Path.cwd() / ".centerstage")).resolve()
MODEL_URL = "https://download.openmmlab.com/mmpose/v1/projects/rtmo/onnx_sdk/rtmo-s_8xb32-600e_body7-640x640-dac2bf74_20231211.zip"
MODEL_SHA256 = "d0703d40d19f3921da51ae725402d5fdae4d2478c7442072d3101bd396f370d8"
MAX_UPLOAD = 2 * 1024**3
MAX_DURATION = 30 * 60
SCHEMA_VERSION = 1

# ============ 新增配置类 ============

@dataclass
class ModelConfig:
    """模型配置"""
    model_url: str = MODEL_URL
    model_sha256: str = MODEL_SHA256
    batch_size: int = 4  # 批处理大小
    use_batch_inference: bool = False  # Experimental wrapper does not implement the live predict/providers contract.
    cache_size: int = 100  # 帧缓存大小
    device: str = "cpu"  # cpu/cuda

@dataclass
class PipelineConfigClass:
    """处理流程配置"""
    adaptive_sampling: bool = True  # 自适应采样
    min_sample_rate: float = 0.5  # 最小采样率
    max_sample_rate: float = 1.0  # 最大采样率
    motion_threshold: float = 50.0  # 运动阈值
    async_mode: bool = False  # 异步处理模式（高级功能）
    num_workers: int = 2  # 异步工作进程数

@dataclass
class ScoringConfig:
    """C位评分配置"""
    use_enhanced_scoring: bool = False  # Experimental scorer returns people, not center IDs; retain the live scorer.
    history_size: int = 5  # 时序历史窗口
    temporal_weight: float = 0.3  # 时序平滑权重
    motion_weight: float = 0.15  # 运动分析权重
    scene_aware: bool = True  # 场景感知
    adaptive_weights: bool = True  # 自适应权重

@dataclass
class AppearanceConfig:
    """外观匹配配置（GarmentLinker v2.0）"""
    max_distance: float = 0.12
    margin: float = 0.04
    min_confidence: float = 0.35
    max_gap: float = 12.0
    gallery_size: int = 24
    votes_needed: int = 4

@dataclass
class PerformanceConfig:
    """性能配置"""
    target_realtime_factor: float = 5.0  # 目标实时倍率
    max_memory_mb: int = 4096  # 最大内存使用(MB)
    enable_profiling: bool = False  # 性能分析
    log_level: str = "INFO"  # DEBUG/INFO/WARNING/ERROR

@dataclass
class SystemConfig:
    """系统配置"""
    data_dir: Path = field(default_factory=lambda: DATA)
    max_upload_size: int = MAX_UPLOAD
    max_duration: int = MAX_DURATION
    schema_version: int = SCHEMA_VERSION

# ============ 全局配置实例 ============

class CenterStageConfig:
    """CenterStage全局配置管理器"""

    def __init__(self):
        self.model = ModelConfig()
        self.pipeline = PipelineConfigClass()
        self.scoring = ScoringConfig()
        self.appearance = AppearanceConfig()
        self.performance = PerformanceConfig()
        self.system = SystemConfig()

        # 从环境变量加载覆盖配置
        self._load_from_env()

    def _load_from_env(self):
        """从环境变量加载配置"""
        # 模型配置
        if batch_size := os.getenv("CS_BATCH_SIZE"):
            self.model.batch_size = int(batch_size)
        if use_batch := os.getenv("CS_USE_BATCH_INFERENCE"):
            self.model.use_batch_inference = use_batch.lower() == "true"

        # 性能配置
        if target_rt := os.getenv("CS_TARGET_REALTIME"):
            self.performance.target_realtime_factor = float(target_rt)
        if log_level := os.getenv("CS_LOG_LEVEL"):
            self.performance.log_level = log_level.upper()

        # Pipeline配置
        if async_mode := os.getenv("CS_ASYNC_MODE"):
            self.pipeline.async_mode = async_mode.lower() == "true"
        if self.model.use_batch_inference or self.pipeline.async_mode:
            raise ValueError('批量 / 异步实验流程未接入当前服务，请移除 CS_USE_BATCH_INFERENCE / CS_ASYNC_MODE；使用默认单帧流程')

    def get_dict(self) -> dict:
        """获取配置字典"""
        return {
            "model": self.model.__dict__,
            "pipeline": self.pipeline.__dict__,
            "scoring": self.scoring.__dict__,
            "appearance": self.appearance.__dict__,
            "performance": self.performance.__dict__,
            "system": {k: str(v) if isinstance(v, Path) else v
                      for k, v in self.system.__dict__.items()}
        }

    def update(self, **kwargs):
        """运行时更新配置"""
        for section, values in kwargs.items():
            if hasattr(self, section):
                config_obj = getattr(self, section)
                for key, value in values.items():
                    if hasattr(config_obj, key):
                        setattr(config_obj, key, value)

# 全局配置单例
_global_config: Optional[CenterStageConfig] = None

def get_config() -> CenterStageConfig:
    """获取全局配置实例"""
    global _global_config
    if _global_config is None:
        _global_config = CenterStageConfig()
    return _global_config

def reset_config():
    """重置配置（主要用于测试）"""
    global _global_config
    _global_config = None
