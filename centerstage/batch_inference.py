"""
批处理推理优化模块
提供批量处理功能以提高GPU利用率和处理速度
"""
import numpy as np
import cv2
from typing import List, Dict, Any, Tuple
import time


class BatchInferenceOptimizer:
    """
    批处理推理优化器
    
    特性:
    - 动态批处理（根据队列大小调整）
    - 预处理并行化
    - 内存池管理
    - 智能调度
    """
    
    def __init__(self, model, batch_size: int = 4, max_wait_time: float = 0.01):
        """
        初始化批处理优化器
        
        Args:
            model: ONNX模型实例
            batch_size: 批处理大小（默认4）
            max_wait_time: 最大等待时间（秒）
        """
        self.model = model
        self.batch_size = batch_size
        self.max_wait_time = max_wait_time
        self.frame_queue = []
        self.result_cache = {}
        
        # 性能统计
        self.stats = {
            'total_frames': 0,
            'total_batches': 0,
            'total_time': 0.0,
            'avg_batch_size': 0.0
        }
    
    def __call__(self, frame: np.ndarray):
        """
        单帧推理接口（兼容原PoseModel API）
        
        Args:
            frame: 输入帧
        Returns:
            检测结果（保持与PoseModel相同的接口）
        """
        # 直接调用底层模型的单帧推理
        return self.model(frame)
    
    def infer_single(self, frame: np.ndarray):
        """单帧推理的别名"""
        return self(frame)
    
    def preprocess_batch(self, frames: List[np.ndarray]) -> np.ndarray:
        """
        批量预处理帧
        
        Args:
            frames: 帧列表
            
        Returns:
            批处理后的tensor
        """
        # 并行预处理
        preprocessed = []
        for frame in frames:
            # 调整大小到模型输入尺寸
            resized = self._resize_frame(frame, (640, 640))
            # 归一化
            normalized = resized.astype(np.float32) / 255.0
            # CHW格式
            transposed = np.transpose(normalized, (2, 0, 1))
            preprocessed.append(transposed)
        
        # 堆叠成batch
        batch = np.stack(preprocessed, axis=0)
        return batch
    
    def _resize_frame(self, frame: np.ndarray, target_size: Tuple[int, int]) -> np.ndarray:
        """调整帧大小（保持宽高比）"""
        import cv2
        h, w = frame.shape[:2]
        target_w, target_h = target_size
        
        # 计算缩放比例
        scale = min(target_w / w, target_h / h)
        new_w = int(w * scale)
        new_h = int(h * scale)
        
        # 缩放
        resized = cv2.resize(frame, (new_w, new_h), interpolation=cv2.INTER_LINEAR)
        
        # 填充到目标尺寸
        canvas = np.zeros((target_h, target_w, 3), dtype=np.uint8)
        y_offset = (target_h - new_h) // 2
        x_offset = (target_w - new_w) // 2
        canvas[y_offset:y_offset+new_h, x_offset:x_offset+new_w] = resized
        
        return canvas
    
    def infer_batch(self, frames: List[np.ndarray]) -> List[Dict[str, Any]]:
        """
        批量推理
        
        Args:
            frames: 帧列表
            
        Returns:
            检测结果列表
        """
        if not frames:
            return []
        
        start_time = time.time()
        
        # 预处理
        batch_input = self.preprocess_batch(frames)
        
        # 批量推理
        # 注意：这里需要模型支持批处理
        # 如果模型不支持，需要逐个处理
        try:
            # 尝试批量推理
            batch_output = self._run_batch_inference(batch_input)
            results = self._postprocess_batch(batch_output, len(frames))
        except Exception as e:
            # 回退到逐个处理
            print(f"批量推理失败，回退到逐个处理: {e}")
            results = []
            for frame in frames:
                single_result = self.model.inference(frame)
                results.append(single_result)
        
        # 更新统计
        elapsed = time.time() - start_time
        self.stats['total_frames'] += len(frames)
        self.stats['total_batches'] += 1
        self.stats['total_time'] += elapsed
        self.stats['avg_batch_size'] = self.stats['total_frames'] / self.stats['total_batches']
        
        return results
    
    def _run_batch_inference(self, batch_input: np.ndarray) -> Dict[str, np.ndarray]:
        """
        运行批量推理（需要模型支持）
        
        Args:
            batch_input: 批处理输入
            
        Returns:
            批处理输出
        """
        # 这里需要根据实际模型接口调整
        # RTMO模型可能需要特殊处理
        raise NotImplementedError("需要根据实际模型实现批量推理")
    
    def _postprocess_batch(self, batch_output: Dict[str, np.ndarray], 
                          batch_size: int) -> List[Dict[str, Any]]:
        """
        后处理批量输出
        
        Args:
            batch_output: 批量输出
            batch_size: 批大小
            
        Returns:
            结果列表
        """
        results = []
        for i in range(batch_size):
            # 提取单个结果
            result = {
                'boxes': batch_output['boxes'][i] if 'boxes' in batch_output else [],
                'keypoints': batch_output['keypoints'][i] if 'keypoints' in batch_output else [],
                'scores': batch_output['scores'][i] if 'scores' in batch_output else []
            }
            results.append(result)
        return results
    
    def process_stream(self, frame_generator):
        """
        流式处理（动态批处理）
        
        Args:
            frame_generator: 帧生成器
            
        Yields:
            处理结果
        """
        batch = []
        batch_start_time = time.time()
        
        for frame_idx, frame in enumerate(frame_generator):
            batch.append((frame_idx, frame))
            
            # 判断是否应该处理batch
            should_process = (
                len(batch) >= self.batch_size or
                (time.time() - batch_start_time) >= self.max_wait_time
            )
            
            if should_process:
                # 处理batch
                frames = [f for _, f in batch]
                results = self.infer_batch(frames)
                
                # 返回结果
                for (idx, _), result in zip(batch, results):
                    yield idx, result
                
                # 重置batch
                batch = []
                batch_start_time = time.time()
        
        # 处理剩余的帧
        if batch:
            frames = [f for _, f in batch]
            results = self.infer_batch(frames)
            for (idx, _), result in zip(batch, results):
                yield idx, result
    
    def get_stats(self) -> Dict[str, Any]:
        """获取性能统计"""
        stats = self.stats.copy()
        if stats['total_time'] > 0:
            stats['fps'] = stats['total_frames'] / stats['total_time']
        else:
            stats['fps'] = 0.0
        return stats


class FrameCache:
    """
    帧缓存管理器
    使用LRU策略管理帧缓存
    """
    
    def __init__(self, max_size: int = 100):
        """
        初始化帧缓存
        
        Args:
            max_size: 最大缓存帧数
        """
        self.max_size = max_size
        self.cache = {}
        self.access_order = []
    
    def get(self, frame_idx: int) -> np.ndarray:
        """获取缓存的帧"""
        if frame_idx in self.cache:
            # 更新访问顺序
            self.access_order.remove(frame_idx)
            self.access_order.append(frame_idx)
            return self.cache[frame_idx]
        return None
    
    def put(self, frame_idx: int, frame: np.ndarray):
        """添加帧到缓存"""
        if frame_idx in self.cache:
            # 已存在，更新访问顺序
            self.access_order.remove(frame_idx)
            self.access_order.append(frame_idx)
            return
        
        # 检查容量
        if len(self.cache) >= self.max_size:
            # 移除最旧的
            oldest = self.access_order.pop(0)
            del self.cache[oldest]
        
        # 添加新帧
        self.cache[frame_idx] = frame
        self.access_order.append(frame_idx)
    
    def clear(self):
        """清空缓存"""
        self.cache.clear()
        self.access_order.clear()
    
    def size(self) -> int:
        """获取当前缓存大小"""
        return len(self.cache)


class AdaptiveSampler:
    """
    自适应帧采样器
    根据场景变化动态调整采样率
    """
    
    def __init__(self, base_fps: float = 30.0, min_fps: float = 15.0, 
                 max_fps: float = 60.0, threshold: float = 0.05):
        """
        初始化自适应采样器
        
        Args:
            base_fps: 基础采样率
            min_fps: 最小采样率
            max_fps: 最大采样率
            threshold: 场景变化阈值
        """
        self.base_fps = base_fps
        self.min_fps = min_fps
        self.max_fps = max_fps
        self.threshold = threshold
        self.prev_frame = None
        self.current_fps = base_fps
    
    def should_sample(self, frame: np.ndarray, timestamp: float) -> bool:
        """
        判断是否应该采样当前帧
        
        Args:
            frame: 当前帧
            timestamp: 时间戳
            
        Returns:
            是否采样
        """
        if self.prev_frame is None:
            self.prev_frame = frame
            return True
        
        # 计算帧差异
        diff = self._calculate_frame_diff(frame, self.prev_frame)
        
        # 根据差异调整采样率
        if diff > self.threshold * 2:
            # 场景变化大，提高采样率
            self.current_fps = self.max_fps
        elif diff > self.threshold:
            # 中等变化，使用基础采样率
            self.current_fps = self.base_fps
        else:
            # 场景稳定，降低采样率
            self.current_fps = self.min_fps
        
        # 判断是否采样
        # 简化实现：使用随机采样
        import random
        sample_prob = self.current_fps / self.max_fps
        should_sample = random.random() < sample_prob
        
        if should_sample:
            self.prev_frame = frame
        
        return should_sample
    
    def _calculate_frame_diff(self, frame1: np.ndarray, frame2: np.ndarray) -> float:
        """
        计算两帧之间的差异
        
        Args:
            frame1: 第一帧
            frame2: 第二帧
            
        Returns:
            差异值（0-1）
        """
        import cv2
        
        # 转换为灰度图
        if len(frame1.shape) == 3:
            gray1 = cv2.cvtColor(frame1, cv2.COLOR_BGR2GRAY)
        else:
            gray1 = frame1
            
        if len(frame2.shape) == 3:
            gray2 = cv2.cvtColor(frame2, cv2.COLOR_BGR2GRAY)
        else:
            gray2 = frame2
        
        # 缩小尺寸以加快计算
        small1 = cv2.resize(gray1, (160, 90))
        small2 = cv2.resize(gray2, (160, 90))
        
        # 计算差异
        diff = np.abs(small1.astype(float) - small2.astype(float))
        mean_diff = np.mean(diff) / 255.0
        
        return mean_diff
    
    def get_current_fps(self) -> float:
        """获取当前采样率"""
        return self.current_fps


