#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
测试优化后的 x_statsig_id 生成策略
验证主要策略（自主生成）+ 备用策略（PHP接口）的降级重试机制
"""

import sys
import time
import json
import requests
from pathlib import Path

# 添加项目根目录到 Python 路径
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

def test_primary_strategy():
    """测试主要策略：自主生成 x_statsig_id"""
    print("=" * 60)
    print("🧪 测试主要策略：自主生成 x_statsig_id")
    print("=" * 60)
    
    try:
        from app import get_x_statsig_id_primary
        
        result = get_x_statsig_id_primary()
        
        if result['success']:
            print(f"✅ 主要策略成功")
            print(f"   生成方法: {result['method']}")
            print(f"   x_statsig_id: {result['x_statsig_id'][:50]}...")
            print(f"   长度: {len(result['x_statsig_id'])} 字符")
            return True
        else:
            print(f"❌ 主要策略失败: {result['error']}")
            return False
            
    except Exception as e:
        print(f"❌ 主要策略异常: {e}")
        return False

def test_fallback_strategy():
    """测试备用策略：PHP 接口获取 x_statsig_id"""
    print("\n" + "=" * 60)
    print("🧪 测试备用策略：PHP 接口获取 x_statsig_id")
    print("=" * 60)
    
    try:
        from app import get_x_statsig_id_fallback
        
        result = get_x_statsig_id_fallback()
        
        if result['success']:
            print(f"✅ 备用策略成功")
            print(f"   生成方法: {result['method']}")
            print(f"   x_statsig_id: {result['x_statsig_id'][:50]}...")
            print(f"   长度: {len(result['x_statsig_id'])} 字符")
            return True
        else:
            print(f"❌ 备用策略失败: {result['error']}")
            return False
            
    except Exception as e:
        print(f"❌ 备用策略异常: {e}")
        return False

def test_combined_strategy():
    """测试组合策略：优先主要策略，失败时自动降级"""
    print("\n" + "=" * 60)
    print("🧪 测试组合策略：主要策略 + 备用策略")
    print("=" * 60)
    
    try:
        from app import get_x_statsig_id
        
        print("正在执行组合策略...")
        start_time = time.time()
        
        x_statsig_id = get_x_statsig_id()
        
        end_time = time.time()
        duration = end_time - start_time
        
        if x_statsig_id and not x_statsig_id.startswith("fallback-statsig-id-"):
            print(f"✅ 组合策略成功")
            print(f"   x_statsig_id: {x_statsig_id[:50]}...")
            print(f"   长度: {len(x_statsig_id)} 字符")
            print(f"   耗时: {duration:.2f} 秒")
            return True
        else:
            print(f"⚠️  组合策略使用了默认值")
            print(f"   x_statsig_id: {x_statsig_id[:50]}...")
            return False
            
    except Exception as e:
        print(f"❌ 组合策略异常: {e}")
        return False

def test_headers_generation():
    """测试请求头生成"""
    print("\n" + "=" * 60)
    print("🧪 测试请求头生成")
    print("=" * 60)
    
    try:
        from app import get_default_headers
        
        # 测试普通请求头生成
        print("测试普通请求头生成...")
        headers1 = get_default_headers()
        
        if 'X-Statsig-Id' in headers1:
            print(f"✅ 普通请求头生成成功")
            print(f"   X-Statsig-Id: {headers1['X-Statsig-Id'][:50]}...")
        else:
            print(f"❌ 普通请求头缺少 X-Statsig-Id")
            return False
        
        # 测试强制刷新请求头生成
        print("\n测试强制刷新请求头生成...")
        headers2 = get_default_headers(force_refresh_statsig=True)
        
        if 'X-Statsig-Id' in headers2:
            print(f"✅ 强制刷新请求头生成成功")
            print(f"   X-Statsig-Id: {headers2['X-Statsig-Id'][:50]}...")
            
            # 检查是否与普通生成的不同（可能相同，但至少应该是有效的）
            if headers1['X-Statsig-Id'] != headers2['X-Statsig-Id']:
                print(f"   ℹ️  强制刷新生成了不同的 X-Statsig-Id")
            else:
                print(f"   ℹ️  强制刷新生成了相同的 X-Statsig-Id（正常情况）")
        else:
            print(f"❌ 强制刷新请求头缺少 X-Statsig-Id")
            return False
            
        return True
        
    except Exception as e:
        print(f"❌ 请求头生成异常: {e}")
        return False

def test_smart_retry_mechanism():
    """测试智能重试机制（模拟）"""
    print("\n" + "=" * 60)
    print("🧪 测试智能重试机制（模拟）")
    print("=" * 60)
    
    try:
        from app import smart_grok_request_with_fallback
        
        # 模拟一个简单的请求函数
        def mock_request_success(**kwargs):
            class MockResponse:
                def __init__(self):
                    self.status_code = 200
                    self.text = "Success"
            return MockResponse()
        
        def mock_request_failure(**kwargs):
            class MockResponse:
                def __init__(self):
                    self.status_code = 403
                    self.text = "Forbidden"
            return MockResponse()
        
        # 测试成功情况
        print("测试成功请求...")
        response1 = smart_grok_request_with_fallback(mock_request_success)
        if response1.status_code == 200:
            print("✅ 成功请求测试通过")
        else:
            print("❌ 成功请求测试失败")
            return False
        
        # 测试失败情况（会触发重试）
        print("\n测试失败请求（触发重试）...")
        response2 = smart_grok_request_with_fallback(mock_request_failure)
        if response2.status_code == 403:
            print("✅ 失败请求测试通过（正确返回失败状态）")
        else:
            print("❌ 失败请求测试异常")
            return False
            
        return True
        
    except Exception as e:
        print(f"❌ 智能重试机制测试异常: {e}")
        return False

def main():
    """主测试函数"""
    print("🚀 开始测试优化后的 x_statsig_id 生成策略")
    print("=" * 80)
    
    test_results = []
    
    # 执行各项测试
    test_results.append(("主要策略测试", test_primary_strategy()))
    test_results.append(("备用策略测试", test_fallback_strategy()))
    test_results.append(("组合策略测试", test_combined_strategy()))
    test_results.append(("请求头生成测试", test_headers_generation()))
    test_results.append(("智能重试机制测试", test_smart_retry_mechanism()))
    
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
    
    if passed == total:
        print("🎉 所有测试都通过！优化策略工作正常。")
        return True
    else:
        print("⚠️  部分测试失败，请检查相关功能。")
        return False

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
