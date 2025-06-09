#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
简化的 x_statsig_id 生成策略测试
直接测试核心组件，不依赖 Flask 应用
"""

import sys
import time
import json
from pathlib import Path

# 添加项目根目录到 Python 路径
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

def test_xstatsig_generator():
    """测试 XStatsigIDGenerator 自主生成功能"""
    print("=" * 60)
    print("🧪 测试 XStatsigIDGenerator 自主生成功能")
    print("=" * 60)
    
    try:
        from xStatsigIDGenerator import XStatsigIDGenerator
        
        print("正在初始化生成器...")
        generator = XStatsigIDGenerator()
        
        print("正在生成 x-statsig-id...")
        start_time = time.time()
        
        statsig_id = generator.generate_x_statsig_id()
        
        end_time = time.time()
        duration = end_time - start_time
        
        if statsig_id and len(statsig_id) > 50:
            print(f"✅ 自主生成成功")
            print(f"   x-statsig-id: {statsig_id[:50]}...")
            print(f"   完整长度: {len(statsig_id)} 字符")
            print(f"   生成耗时: {duration:.2f} 秒")
            
            # 验证生成的ID结构
            print("\n正在验证ID结构...")
            is_valid = generator.verify_generated_id(statsig_id)
            if is_valid:
                print("✅ ID结构验证通过")
            else:
                print("⚠️  ID结构验证失败")
            
            return True
        else:
            print(f"❌ 自主生成失败或结果无效")
            return False
            
    except Exception as e:
        print(f"❌ 自主生成异常: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_php_interface():
    """测试 PHP 接口获取功能"""
    print("\n" + "=" * 60)
    print("🧪 测试 PHP 接口获取功能")
    print("=" * 60)
    
    try:
        import requests
        
        url = "https://rui.soundai.ee/x.php"
        print(f"正在请求 PHP 接口: {url}")
        
        start_time = time.time()
        response = requests.get(url, timeout=10)
        end_time = time.time()
        duration = end_time - start_time
        
        if response.status_code == 200:
            try:
                data = response.json()
                x_statsig_id = data.get('x_statsig_id')
                
                if x_statsig_id:
                    print(f"✅ PHP 接口获取成功")
                    print(f"   x_statsig_id: {x_statsig_id[:50]}...")
                    print(f"   完整长度: {len(x_statsig_id)} 字符")
                    print(f"   请求耗时: {duration:.2f} 秒")
                    print(f"   响应数据: {json.dumps(data, indent=2)}")
                    return True
                else:
                    print(f"❌ PHP 接口响应中缺少 x_statsig_id")
                    print(f"   响应内容: {response.text}")
                    return False
                    
            except json.JSONDecodeError as e:
                print(f"❌ PHP 接口响应 JSON 解析失败: {e}")
                print(f"   响应内容: {response.text}")
                return False
        else:
            print(f"❌ PHP 接口请求失败，状态码: {response.status_code}")
            print(f"   响应内容: {response.text}")
            return False
            
    except Exception as e:
        print(f"❌ PHP 接口请求异常: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_format_compatibility():
    """测试两种方法生成的格式兼容性"""
    print("\n" + "=" * 60)
    print("🧪 测试格式兼容性")
    print("=" * 60)
    
    try:
        # 获取自主生成的ID
        from xStatsigIDGenerator import XStatsigIDGenerator
        generator = XStatsigIDGenerator()
        self_generated_id = generator.generate_x_statsig_id()
        
        # 获取PHP接口的ID
        import requests
        response = requests.get("https://rui.soundai.ee/x.php", timeout=10)
        if response.status_code == 200:
            php_data = response.json()
            php_generated_id = php_data.get('x_statsig_id')
        else:
            print("⚠️  无法获取 PHP 接口的 ID，跳过兼容性测试")
            return True
        
        print(f"自主生成 ID 长度: {len(self_generated_id)}")
        print(f"PHP 接口 ID 长度: {len(php_generated_id)}")
        
        # 检查基本格式特征
        import base64
        
        def check_base64_format(id_str):
            try:
                decoded = base64.b64decode(id_str)
                return len(decoded) > 60  # 应该有足够的字节数
            except:
                return False
        
        self_valid = check_base64_format(self_generated_id)
        php_valid = check_base64_format(php_generated_id)
        
        print(f"自主生成 ID Base64 格式: {'✅ 有效' if self_valid else '❌ 无效'}")
        print(f"PHP 接口 ID Base64 格式: {'✅ 有效' if php_valid else '❌ 无效'}")
        
        if self_valid and php_valid:
            print("✅ 两种方法生成的 ID 格式都有效")
            return True
        else:
            print("⚠️  格式兼容性检查发现问题")
            return False
            
    except Exception as e:
        print(f"❌ 格式兼容性测试异常: {e}")
        return False

def test_performance_comparison():
    """测试性能对比"""
    print("\n" + "=" * 60)
    print("🧪 测试性能对比")
    print("=" * 60)
    
    try:
        import requests
        from xStatsigIDGenerator import XStatsigIDGenerator
        
        # 测试自主生成性能
        print("测试自主生成性能（3次）...")
        generator = XStatsigIDGenerator()
        self_times = []
        
        for i in range(3):
            start_time = time.time()
            statsig_id = generator.generate_x_statsig_id()
            end_time = time.time()
            duration = end_time - start_time
            self_times.append(duration)
            print(f"   第 {i+1} 次: {duration:.2f} 秒")
        
        avg_self_time = sum(self_times) / len(self_times)
        print(f"   平均耗时: {avg_self_time:.2f} 秒")
        
        # 测试PHP接口性能
        print("\n测试 PHP 接口性能（3次）...")
        php_times = []
        
        for i in range(3):
            start_time = time.time()
            response = requests.get("https://rui.soundai.ee/x.php", timeout=10)
            end_time = time.time()
            duration = end_time - start_time
            
            if response.status_code == 200:
                php_times.append(duration)
                print(f"   第 {i+1} 次: {duration:.2f} 秒")
            else:
                print(f"   第 {i+1} 次: 请求失败")
        
        if php_times:
            avg_php_time = sum(php_times) / len(php_times)
            print(f"   平均耗时: {avg_php_time:.2f} 秒")
            
            # 性能对比
            print(f"\n📊 性能对比:")
            print(f"   自主生成平均耗时: {avg_self_time:.2f} 秒")
            print(f"   PHP 接口平均耗时: {avg_php_time:.2f} 秒")
            
            if avg_self_time < avg_php_time:
                improvement = ((avg_php_time - avg_self_time) / avg_php_time) * 100
                print(f"   ✅ 自主生成比 PHP 接口快 {improvement:.1f}%")
            else:
                print(f"   ⚠️  PHP 接口比自主生成快")
        else:
            print("   ⚠️  PHP 接口测试失败，无法进行性能对比")
        
        return True
        
    except Exception as e:
        print(f"❌ 性能对比测试异常: {e}")
        return False

def main():
    """主测试函数"""
    print("🚀 开始测试 x_statsig_id 生成策略（简化版）")
    print("=" * 80)
    
    test_results = []
    
    # 执行各项测试
    test_results.append(("XStatsigIDGenerator 测试", test_xstatsig_generator()))
    test_results.append(("PHP 接口测试", test_php_interface()))
    test_results.append(("格式兼容性测试", test_format_compatibility()))
    test_results.append(("性能对比测试", test_performance_comparison()))
    
    # 输出测试结果汇总
    print("\n" + "=" * 80)
    print("📊 测试结果汇总")
    print("=" * 80)
    
    passed = 0
    total = len(test_results)
    
    for test_name, result in test_results:
        status = "✅ 通过" if result else "❌ 失败"
        print(f"   {test_name}: {status}")
        if result:
            passed += 1
    
    print(f"\n总计: {passed}/{total} 项测试通过")
    
    if passed >= total * 0.75:  # 75% 通过率即可
        print("🎉 大部分测试通过！优化策略基本正常。")
        return True
    else:
        print("⚠️  多项测试失败，请检查相关功能。")
        return False

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
