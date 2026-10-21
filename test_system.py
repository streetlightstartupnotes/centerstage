#!/usr/bin/env python3
"""
测试自动识别系统
"""
import sys
import cv2
import numpy as np

print("=" * 60)
print("🧪 测试 CenterStage V2 自动识别系统")
print("=" * 60)

# 测试基础导入
print("\n1. 测试基础模块导入...")
try:
    from centerstage.agent_identifier import AgentDrivenIdentifier
    print("  ✓ AgentDrivenIdentifier")
except Exception as e:
    print(f"  ✗ AgentDrivenIdentifier: {e}")
    sys.exit(1)

try:
    from centerstage.center_detector import CenterPositionDetector
    print("  ✓ CenterPositionDetector")
except Exception as e:
    print(f"  ✗ CenterPositionDetector: {e}")
    sys.exit(1)

try:
    from centerstage.video_processor_v2 import VideoProcessorV2
    print("  ✓ VideoProcessorV2")
except Exception as e:
    print(f"  ✗ VideoProcessorV2: {e}")
    sys.exit(1)

# 测试识别器初始化
print("\n2. 测试识别器初始化...")
try:
    identifier = AgentDrivenIdentifier()
    print(f"  ✓ 识别器创建成功")
    print(f"  ✓ 可用成员: {len(identifier.available_members)}个")
except Exception as e:
    print(f"  ✗ 识别器初始化失败: {e}")
    sys.exit(1)

# 测试特征提取
print("\n3. 测试人脸特征提取...")
try:
    # 创建测试图像
    test_face = np.random.randint(0, 255, (128, 128, 3), dtype=np.uint8)
    feature = identifier._extract_face_feature(test_face)
    print(f"  ✓ 特征维度: {feature.shape[0]}维")
    print(f"  ✓ 特征提取成功")
except Exception as e:
    print(f"  ✗ 特征提取失败: {e}")
    sys.exit(1)

# 测试相似度计算
print("\n4. 测试特征相似度计算...")
try:
    feat1 = np.random.rand(94)
    feat2 = np.random.rand(94)
    similarity = identifier._compute_similarity(feat1, feat2)
    print(f"  ✓ 相似度: {similarity:.4f}")
except Exception as e:
    print(f"  ✗ 相似度计算失败: {e}")
    sys.exit(1)

# 测试身份处理
print("\n5. 测试身份处理流程...")
try:
    # 模拟检测
    test_frame = np.random.randint(0, 255, (720, 1280, 3), dtype=np.uint8)
    bbox = (100, 100, 200, 200)
    
    identity_id = identifier.process_detection(1, bbox, test_frame)
    print(f"  ✓ Identity ID: {identity_id}")
    print(f"  ✓ 已创建身份数: {len(identifier.identities)}")
except Exception as e:
    print(f"  ✗ 身份处理失败: {e}")
    sys.exit(1)

# 测试自动命名
print("\n6. 测试自动命名...")
try:
    # 添加一些模拟出现
    for i in range(10):
        identifier.identities[1]['appearances'] += 1
    
    identifier.auto_assign_names()
    name = identifier.get_member_name(1)
    print(f"  ✓ 自动分配名字: {name}")
except Exception as e:
    print(f"  ✗ 自动命名失败: {e}")
    sys.exit(1)

print("\n" + "=" * 60)
print("✅ 所有测试通过！系统可以正常运行")
print("=" * 60)
print("\n💡 下一步:")
print("  1. 运行: python3 run_v2.py")
print("  2. 访问: http://127.0.0.1:8640")
print("  3. 上传视频进行测试")
