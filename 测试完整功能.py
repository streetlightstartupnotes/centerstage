#!/usr/bin/env python3
"""
完整功能测试脚本
验证所有核心功能是否正常工作
"""
import sys
import asyncio
from pathlib import Path

def test_imports():
    """测试1: 检查所有模块导入"""
    print("=" * 60)
    print("测试1: 检查模块导入")
    print("=" * 60)
    
    modules = [
        ('centerstage.智能识别引擎', 'SmartIdentifier'),
        ('centerstage.智能识别集成', 'auto_identify_members'),
        ('centerstage.智能识别API', 'add_smart_identification_routes'),
        ('centerstage.pipeline', 'AnalysisPipeline'),
        ('centerstage.engine', 'Manager'),
        ('centerstage.scoring', 'CenterScorer'),
        ('centerstage.appearance', 'GarmentLinker'),
    ]
    
    all_passed = True
    for module_name, class_name in modules:
        try:
            module = __import__(module_name, fromlist=[class_name])
            getattr(module, class_name)
            print(f"  ✓ {module_name}.{class_name}")
        except Exception as e:
            print(f"  ✗ {module_name}.{class_name}: {e}")
            all_passed = False
    
    print()
    return all_passed

def test_smart_identifier():
    """测试2: 智能识别器"""
    print("=" * 60)
    print("测试2: 智能识别器")
    print("=" * 60)
    
    try:
        from centerstage.智能识别引擎 import SmartIdentifier
        
        # 创建识别器
        identifier = SmartIdentifier(Path('.centerstage/test'))
        print("  ✓ 识别器创建成功")
        
        # 测试女团识别
        async def test_identify():
            roster = await identifier.identify_group("A2O LITE NEON初舞台", "李秀满女团")
            return roster
        
        roster = asyncio.run(test_identify())
        if roster and len(roster) == 9:
            print(f"  ✓ 女团识别成功: {len(roster)}名成员")
            print(f"    成员: {', '.join(roster[:3])}...")
        else:
            print(f"  ✗ 女团识别失败")
            return False
        
        # 测试自动匹配
        track_stats = {
            f"1-{i}": {'appearances': 100 - i * 5}
            for i in range(9)
        }
        identifier.roster = roster
        mappings = identifier.auto_match_tracks(track_stats)
        
        if len(mappings) == 9:
            print(f"  ✓ 自动匹配成功: {len(mappings)}个track")
            print(f"    示例: 1-0 -> {mappings.get('1-0')}")
        else:
            print(f"  ✗ 自动匹配失败")
            return False
        
        # 测试手动修正
        identifier.manual_correction("1-0", "TEST_NAME")
        if identifier.get_member_name("1-0") == "TEST_NAME":
            print(f"  ✓ 手动修正成功")
        else:
            print(f"  ✗ 手动修正失败")
            return False
        
        print()
        return True
        
    except Exception as e:
        print(f"  ✗ 测试失败: {e}")
        import traceback
        traceback.print_exc()
        print()
        return False

def test_known_groups():
    """测试3: 已知女团识别"""
    print("=" * 60)
    print("测试3: 已知女团识别")
    print("=" * 60)
    
    try:
        from centerstage.智能识别引擎 import SmartIdentifier
        
        test_cases = [
            ("A2O LITE出道", "A2O", 9),
            ("BLACKPINK演唱会", "BLACKPINK", 4),
            ("TWICE舞台", "TWICE", 9),
            ("AESPA新歌", "AESPA", 4),
            ("IVE表演", "IVE", 6),
            ("NEWJEANS舞台", "NEWJEANS", 5),
        ]
        
        identifier = SmartIdentifier(Path('.centerstage/test'))
        
        for title, expected_group, expected_count in test_cases:
            async def identify():
                return await identifier.identify_group(title, "")
            
            roster = asyncio.run(identify())
            if roster and len(roster) == expected_count:
                print(f"  ✓ {expected_group}: {len(roster)}名成员")
            else:
                print(f"  ✗ {expected_group}: 识别失败")
                return False
        
        print()
        return True
        
    except Exception as e:
        print(f"  ✗ 测试失败: {e}")
        print()
        return False

def test_pipeline_integration():
    """测试4: Pipeline集成"""
    print("=" * 60)
    print("测试4: Pipeline集成")
    print("=" * 60)
    
    try:
        from centerstage.pipeline import PipelineConfig, AnalysisPipeline
        
        # 创建pipeline配置
        config = PipelineConfig(sample_rate=10, tracker='ocsort')
        print(f"  ✓ Pipeline配置创建成功")
        print(f"    采样率: {config.sample_rate}fps")
        print(f"    追踪器: {config.tracker}")
        
        # 创建pipeline
        pipeline = AnalysisPipeline(config)
        print(f"  ✓ Pipeline创建成功")
        
        print()
        return True
        
    except Exception as e:
        print(f"  ✗ 测试失败: {e}")
        print()
        return False

def test_api_structure():
    """测试5: API结构"""
    print("=" * 60)
    print("测试5: API结构")
    print("=" * 60)
    
    try:
        from centerstage.app import create_app
        
        # 创建应用
        app = create_app()
        print(f"  ✓ FastAPI应用创建成功")
        
        # 检查路由
        routes = [route.path for route in app.routes]
        required_routes = [
            '/api/upload',
            '/api/jobs/{identity}',
        ]
        
        for route in required_routes:
            if any(route in r for r in routes):
                print(f"  ✓ 路由存在: {route}")
            else:
                print(f"  ✗ 路由缺失: {route}")
                return False
        
        print()
        return True
        
    except Exception as e:
        print(f"  ✗ 测试失败: {e}")
        import traceback
        traceback.print_exc()
        print()
        return False

def test_static_files():
    """测试6: 静态文件"""
    print("=" * 60)
    print("测试6: 静态文件")
    print("=" * 60)
    
    try:
        static_dir = Path(__file__).parent / "centerstage" / "static"
        index_file = static_dir / "index.html"
        
        if index_file.exists():
            content = index_file.read_text()
            
            # 检查关键功能
            checks = [
                ('上传功能', 'fileInput'),
                ('进度条', 'progressFill'),
                ('排行榜', 'rankingsList'),
                ('成员数', 'memberCount'),
                ('当前C位', 'currentCenterName'),
            ]
            
            all_passed = True
            for name, keyword in checks:
                if keyword in content:
                    print(f"  ✓ {name}: {keyword}")
                else:
                    print(f"  ✗ {name}缺失: {keyword}")
                    all_passed = False
            
            print()
            return all_passed
        else:
            print(f"  ✗ index.html不存在")
            print()
            return False
            
    except Exception as e:
        print(f"  ✗ 测试失败: {e}")
        print()
        return False

def main():
    """运行所有测试"""
    print("\n")
    print("╔" + "=" * 58 + "╗")
    print("║  CenterStage 完整功能测试                              ║")
    print("╚" + "=" * 58 + "╝")
    print()
    
    tests = [
        ("模块导入", test_imports),
        ("智能识别器", test_smart_identifier),
        ("已知女团", test_known_groups),
        ("Pipeline集成", test_pipeline_integration),
        ("API结构", test_api_structure),
        ("静态文件", test_static_files),
    ]
    
    results = []
    for name, test_func in tests:
        try:
            passed = test_func()
            results.append((name, passed))
        except Exception as e:
            print(f"测试 {name} 发生异常: {e}")
            import traceback
            traceback.print_exc()
            results.append((name, False))
    
    # 汇总结果
    print("=" * 60)
    print("测试结果汇总")
    print("=" * 60)
    
    passed_count = sum(1 for _, passed in results if passed)
    total_count = len(results)
    
    for name, passed in results:
        status = "✓ 通过" if passed else "✗ 失败"
        print(f"  {status}: {name}")
    
    print()
    print(f"总计: {passed_count}/{total_count} 通过")
    print()
    
    if passed_count == total_count:
        print("╔" + "=" * 58 + "╗")
        print("║  ✅ 所有测试通过！系统可以正常运行                    ║")
        print("╚" + "=" * 58 + "╝")
        print()
        print("下一步:")
        print("  1. 启动服务: python -m centerstage serve")
        print("  2. 访问界面: http://127.0.0.1:8640")
        print("  3. 上传视频开始测试")
        return 0
    else:
        print("╔" + "=" * 58 + "╗")
        print("║  ❌ 部分测试失败，请检查错误信息                      ║")
        print("╚" + "=" * 58 + "╝")
        return 1

if __name__ == "__main__":
    sys.exit(main())
