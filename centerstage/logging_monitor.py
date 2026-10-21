"""
日志和监控系统
提供结构化日志、性能监控、指标收集
"""
import logging
import time
import json
from pathlib import Path
from typing import Dict, Any, Optional
from contextlib import contextmanager
from collections import defaultdict
from datetime import datetime


class StructuredLogger:
    """
    结构化日志器
    支持JSON格式日志和性能追踪
    """
    
    def __init__(self, name: str, log_dir: Optional[Path] = None):
        """
        初始化结构化日志器
        
        Args:
            name: 日志器名称
            log_dir: 日志目录
        """
        self.name = name
        self.log_dir = log_dir or Path("~/.centerstage/logs").expanduser()
        self.log_dir.mkdir(parents=True, exist_ok=True)
        
        # 创建标准日志器
        self.logger = logging.getLogger(name)
        self.logger.setLevel(logging.DEBUG)
        
        # 文件处理器
        log_file = self.log_dir / f"{name}.log"
        file_handler = logging.FileHandler(log_file)
        file_handler.setLevel(logging.DEBUG)
        
        # JSON格式处理器
        json_file = self.log_dir / f"{name}.jsonl"
        self.json_handler = logging.FileHandler(json_file)
        self.json_handler.setLevel(logging.INFO)
        
        # 控制台处理器
        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.INFO)
        
        # 格式化
        formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        )
        file_handler.setFormatter(formatter)
        console_handler.setFormatter(formatter)
        
        self.logger.addHandler(file_handler)
        self.logger.addHandler(console_handler)
        self.logger.addHandler(self.json_handler)
    
    def _log_json(self, level: str, message: str, extra: Dict[str, Any] = None):
        """
        记录JSON格式日志
        
        Args:
            level: 日志级别
            message: 消息
            extra: 额外信息
        """
        log_entry = {
            'timestamp': datetime.now().isoformat(),
            'level': level,
            'logger': self.name,
            'message': message,
        }
        
        if extra:
            log_entry.update(extra)
        
        # 写入JSON日志
        json_line = json.dumps(log_entry, ensure_ascii=False)
        self.json_handler.stream.write(json_line + '\n')
        self.json_handler.stream.flush()
    
    def debug(self, message: str, **kwargs):
        """调试日志"""
        self.logger.debug(message)
        self._log_json('DEBUG', message, kwargs)
    
    def info(self, message: str, **kwargs):
        """信息日志"""
        self.logger.info(message)
        self._log_json('INFO', message, kwargs)
    
    def warning(self, message: str, **kwargs):
        """警告日志"""
        self.logger.warning(message)
        self._log_json('WARNING', message, kwargs)
    
    def error(self, message: str, **kwargs):
        """错误日志"""
        self.logger.error(message)
        self._log_json('ERROR', message, kwargs)
    
    def critical(self, message: str, **kwargs):
        """严重错误日志"""
        self.logger.critical(message)
        self._log_json('CRITICAL', message, kwargs)


class PerformanceMonitor:
    """
    性能监控器
    追踪关键性能指标
    """
    
    def __init__(self):
        """初始化性能监控器"""
        self.metrics = defaultdict(list)
        self.timers = {}
        self.counters = defaultdict(int)
    
    @contextmanager
    def timer(self, name: str):
        """
        计时器上下文管理器
        
        Args:
            name: 计时器名称
            
        Usage:
            with monitor.timer('inference'):
                model.infer(frame)
        """
        start_time = time.time()
        yield
        elapsed = time.time() - start_time
        
        self.metrics[name].append(elapsed)
        self.timers[name] = elapsed
    
    def record_metric(self, name: str, value: float):
        """
        记录指标
        
        Args:
            name: 指标名称
            value: 指标值
        """
        self.metrics[name].append(value)
    
    def increment_counter(self, name: str, value: int = 1):
        """
        增加计数器
        
        Args:
            name: 计数器名称
            value: 增加值
        """
        self.counters[name] += value
    
    def get_stats(self, name: str) -> Dict[str, float]:
        """
        获取统计信息
        
        Args:
            name: 指标名称
            
        Returns:
            统计信息（平均值、最小值、最大值等）
        """
        if name not in self.metrics or not self.metrics[name]:
            return {}
        
        values = self.metrics[name]
        return {
            'count': len(values),
            'mean': sum(values) / len(values),
            'min': min(values),
            'max': max(values),
            'total': sum(values)
        }
    
    def get_all_stats(self) -> Dict[str, Any]:
        """获取所有统计信息"""
        stats = {
            'metrics': {},
            'counters': dict(self.counters),
            'timers': dict(self.timers)
        }
        
        for name in self.metrics:
            stats['metrics'][name] = self.get_stats(name)
        
        return stats
    
    def reset(self):
        """重置所有指标"""
        self.metrics.clear()
        self.timers.clear()
        self.counters.clear()
    
    def export_to_file(self, filepath: Path):
        """
        导出到文件
        
        Args:
            filepath: 文件路径
        """
        stats = self.get_all_stats()
        with open(filepath, 'w') as f:
            json.dump(stats, f, indent=2)


class MetricsCollector:
    """
    指标收集器
    收集系统和业务指标
    """
    
    def __init__(self, flush_interval: int = 60):
        """
        初始化指标收集器
        
        Args:
            flush_interval: 刷新间隔（秒）
        """
        self.flush_interval = flush_interval
        self.metrics = {}
        self.last_flush = time.time()
    
    def record(self, metric_name: str, value: float, tags: Dict[str, str] = None):
        """
        记录指标
        
        Args:
            metric_name: 指标名称
            value: 指标值
            tags: 标签
        """
        key = self._make_key(metric_name, tags)
        
        if key not in self.metrics:
            self.metrics[key] = {
                'name': metric_name,
                'values': [],
                'tags': tags or {}
            }
        
        self.metrics[key]['values'].append({
            'value': value,
            'timestamp': time.time()
        })
        
        # 检查是否需要刷新
        if time.time() - self.last_flush > self.flush_interval:
            self.flush()
    
    def _make_key(self, metric_name: str, tags: Dict[str, str] = None) -> str:
        """
        生成指标键
        
        Args:
            metric_name: 指标名称
            tags: 标签
            
        Returns:
            指标键
        """
        if not tags:
            return metric_name
        
        tag_str = ','.join(f"{k}={v}" for k, v in sorted(tags.items()))
        return f"{metric_name}[{tag_str}]"
    
    def flush(self):
        """刷新指标（写入存储）"""
        # 这里可以实现写入到时序数据库、Prometheus等
        # 简化实现：只打印
        for key, metric in self.metrics.items():
            if metric['values']:
                avg_value = sum(v['value'] for v in metric['values']) / len(metric['values'])
                print(f"Metric: {metric['name']} = {avg_value:.4f} {metric['tags']}")
        
        # 清空
        self.metrics.clear()
        self.last_flush = time.time()
    
    def get_metrics(self) -> Dict[str, Any]:
        """获取当前指标"""
        return dict(self.metrics)


class SystemMonitor:
    """
    系统监控器
    监控CPU、内存、GPU等系统资源
    """
    
    def __init__(self):
        """初始化系统监控器"""
        try:
            import psutil
            self.psutil = psutil
            self.has_psutil = True
        except ImportError:
            self.has_psutil = False
    
    def get_system_metrics(self) -> Dict[str, Any]:
        """
        获取系统指标
        
        Returns:
            系统指标字典
        """
        if not self.has_psutil:
            return {}
        
        import os
        process = self.psutil.Process(os.getpid())
        
        metrics = {
            'cpu': {
                'percent': self.psutil.cpu_percent(interval=0.1),
                'count': self.psutil.cpu_count()
            },
            'memory': {
                'percent': self.psutil.virtual_memory().percent,
                'used_mb': self.psutil.virtual_memory().used / 1024 / 1024,
                'available_mb': self.psutil.virtual_memory().available / 1024 / 1024
            },
            'process': {
                'memory_mb': process.memory_info().rss / 1024 / 1024,
                'cpu_percent': process.cpu_percent()
            }
        }
        
        # GPU信息（如果有）
        try:
            import pynvml
            pynvml.nvmlInit()
            device_count = pynvml.nvmlDeviceGetCount()
            
            metrics['gpu'] = []
            for i in range(device_count):
                handle = pynvml.nvmlDeviceGetHandleByIndex(i)
                info = pynvml.nvmlDeviceGetMemoryInfo(handle)
                util = pynvml.nvmlDeviceGetUtilizationRates(handle)
                
                metrics['gpu'].append({
                    'index': i,
                    'memory_used_mb': info.used / 1024 / 1024,
                    'memory_total_mb': info.total / 1024 / 1024,
                    'utilization_percent': util.gpu
                })
            
            pynvml.nvmlShutdown()
        except:
            pass
        
        return metrics


# 全局实例
_logger = StructuredLogger('centerstage')
_monitor = PerformanceMonitor()
_metrics = MetricsCollector()
_system_monitor = SystemMonitor()


def get_logger(name: str = 'centerstage') -> StructuredLogger:
    """获取日志器"""
    return StructuredLogger(name)


def get_monitor() -> PerformanceMonitor:
    """获取性能监控器"""
    return _monitor


def get_metrics_collector() -> MetricsCollector:
    """获取指标收集器"""
    return _metrics


def get_system_monitor() -> SystemMonitor:
    """获取系统监控器"""
    return _system_monitor

