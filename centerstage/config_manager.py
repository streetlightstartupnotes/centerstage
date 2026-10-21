"""
配置管理系统
支持环境变量、配置文件、运行时配置
"""
import os
import json
from pathlib import Path
from typing import Any, Dict, Optional
from dataclasses import dataclass, asdict


@dataclass
class ModelConfig:
    """模型配置"""
    name: str = "rtmo-s"
    batch_size: int = 4
    input_size: tuple = (640, 640)
    provider: str = "auto"  # auto, cuda, cpu, coreml
    num_threads: int = 2
    use_fp16: bool = False


@dataclass
class PipelineConfig:
    """Pipeline配置"""
    sampling_fps: float = 30.0
    min_fps: float = 15.0
    max_fps: float = 60.0
    adaptive_sampling: bool = True
    scene_change_threshold: float = 0.05
    max_duration: int = 1800  # 30分钟


@dataclass
class ScoringConfig:
    """C位检测配置"""
    use_enhanced: bool = True
    history_size: int = 5
    confidence_threshold: float = 0.67
    score_diff_threshold: float = 0.065
    temporal_alpha: float = 0.16


@dataclass
class AppearanceConfig:
    """跨镜头合并配置"""
    max_distance: float = 0.18
    margin: float = 0.03
    max_gap: float = 18.0
    gallery_size: int = 32
    votes_required: int = 2


@dataclass
class PerformanceConfig:
    """性能配置"""
    use_batch_inference: bool = True
    use_async_pipeline: bool = False
    max_workers: int = 4
    frame_cache_size: int = 100
    enable_profiling: bool = False


@dataclass
class SystemConfig:
    """系统配置"""
    data_dir: Path = Path("~/.centerstage/data").expanduser()
    cache_dir: Path = Path("~/.centerstage/cache").expanduser()
    log_level: str = "INFO"
    enable_metrics: bool = True
    max_concurrent_jobs: int = 3


class ConfigManager:
    """
    配置管理器
    
    优先级：
    1. 运行时参数
    2. 环境变量
    3. 配置文件
    4. 默认值
    """
    
    def __init__(self, config_file: Optional[Path] = None):
        """
        初始化配置管理器
        
        Args:
            config_file: 配置文件路径
        """
        self.config_file = config_file or Path("~/.centerstage/config.json").expanduser()
        
        # 加载配置
        self.model = ModelConfig()
        self.pipeline = PipelineConfig()
        self.scoring = ScoringConfig()
        self.appearance = AppearanceConfig()
        self.performance = PerformanceConfig()
        self.system = SystemConfig()
        
        # 从文件加载
        self.load_from_file()
        
        # 从环境变量加载
        self.load_from_env()
    
    def load_from_file(self):
        """从配置文件加载"""
        if not self.config_file.exists():
            return
        
        try:
            with open(self.config_file, 'r') as f:
                config_data = json.load(f)
            
            # 更新各部分配置
            if 'model' in config_data:
                self._update_config(self.model, config_data['model'])
            
            if 'pipeline' in config_data:
                self._update_config(self.pipeline, config_data['pipeline'])
            
            if 'scoring' in config_data:
                self._update_config(self.scoring, config_data['scoring'])
            
            if 'appearance' in config_data:
                self._update_config(self.appearance, config_data['appearance'])
            
            if 'performance' in config_data:
                self._update_config(self.performance, config_data['performance'])
            
            if 'system' in config_data:
                self._update_config(self.system, config_data['system'])
                
        except Exception as e:
            print(f"加载配置文件失败: {e}")
    
    def load_from_env(self):
        """从环境变量加载"""
        # Model
        if os.getenv('CENTERSTAGE_MODEL_BATCH_SIZE'):
            self.model.batch_size = int(os.getenv('CENTERSTAGE_MODEL_BATCH_SIZE'))
        
        if os.getenv('CENTERSTAGE_MODEL_PROVIDER'):
            self.model.provider = os.getenv('CENTERSTAGE_MODEL_PROVIDER')
        
        if os.getenv('CENTERSTAGE_THREADS'):
            self.model.num_threads = int(os.getenv('CENTERSTAGE_THREADS'))
        
        # Pipeline
        if os.getenv('CENTERSTAGE_SAMPLING_FPS'):
            self.pipeline.sampling_fps = float(os.getenv('CENTERSTAGE_SAMPLING_FPS'))
        
        # Performance
        if os.getenv('CENTERSTAGE_USE_BATCH'):
            self.performance.use_batch_inference =                 os.getenv('CENTERSTAGE_USE_BATCH').lower() == 'true'
        
        if os.getenv('CENTERSTAGE_USE_ASYNC'):
            self.performance.use_async_pipeline =                 os.getenv('CENTERSTAGE_USE_ASYNC').lower() == 'true'
        
        if os.getenv('CENTERSTAGE_MAX_WORKERS'):
            self.performance.max_workers = int(os.getenv('CENTERSTAGE_MAX_WORKERS'))
        
        # System
        if os.getenv('CENTERSTAGE_DATA_DIR'):
            self.system.data_dir = Path(os.getenv('CENTERSTAGE_DATA_DIR'))
        
        if os.getenv('CENTERSTAGE_LOG_LEVEL'):
            self.system.log_level = os.getenv('CENTERSTAGE_LOG_LEVEL')
    
    def _update_config(self, config_obj, config_dict: Dict[str, Any]):
        """
        更新配置对象
        
        Args:
            config_obj: 配置对象
            config_dict: 配置字典
        """
        for key, value in config_dict.items():
            if hasattr(config_obj, key):
                # 类型转换
                current_value = getattr(config_obj, key)
                if isinstance(current_value, Path):
                    value = Path(value)
                elif isinstance(current_value, tuple):
                    value = tuple(value)
                
                setattr(config_obj, key, value)
    
    def save_to_file(self):
        """保存到配置文件"""
        self.config_file.parent.mkdir(parents=True, exist_ok=True)
        
        config_data = {
            'model': asdict(self.model),
            'pipeline': asdict(self.pipeline),
            'scoring': asdict(self.scoring),
            'appearance': asdict(self.appearance),
            'performance': asdict(self.performance),
            'system': asdict(self.system)
        }
        
        # 转换Path为字符串
        def convert_paths(obj):
            if isinstance(obj, dict):
                return {k: convert_paths(v) for k, v in obj.items()}
            elif isinstance(obj, Path):
                return str(obj)
            elif isinstance(obj, tuple):
                return list(obj)
            else:
                return obj
        
        config_data = convert_paths(config_data)
        
        with open(self.config_file, 'w') as f:
            json.dump(config_data, f, indent=2)
    
    def update(self, **kwargs):
        """
        运行时更新配置
        
        Args:
            **kwargs: 配置参数
        """
        for key, value in kwargs.items():
            # 解析配置路径 (如 'model.batch_size')
            parts = key.split('.')
            if len(parts) == 2:
                section, param = parts
                if hasattr(self, section):
                    config_obj = getattr(self, section)
                    if hasattr(config_obj, param):
                        setattr(config_obj, param, value)
    
    def get(self, key: str, default: Any = None) -> Any:
        """
        获取配置值
        
        Args:
            key: 配置键（如 'model.batch_size'）
            default: 默认值
            
        Returns:
            配置值
        """
        parts = key.split('.')
        if len(parts) == 2:
            section, param = parts
            if hasattr(self, section):
                config_obj = getattr(self, section)
                if hasattr(config_obj, param):
                    return getattr(config_obj, param)
        
        return default
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            'model': asdict(self.model),
            'pipeline': asdict(self.pipeline),
            'scoring': asdict(self.scoring),
            'appearance': asdict(self.appearance),
            'performance': asdict(self.performance),
            'system': asdict(self.system)
        }
    
    def __repr__(self) -> str:
        """字符串表示"""
        return json.dumps(self.to_dict(), indent=2, default=str)


# 全局配置实例
_global_config: Optional[ConfigManager] = None


def get_config() -> ConfigManager:
    """获取全局配置"""
    global _global_config
    if _global_config is None:
        _global_config = ConfigManager()
    return _global_config


def init_config(config_file: Optional[Path] = None) -> ConfigManager:
    """
    初始化全局配置
    
    Args:
        config_file: 配置文件路径
        
    Returns:
        配置管理器
    """
    global _global_config
    _global_config = ConfigManager(config_file)
    return _global_config

