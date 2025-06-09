#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
使用自主生成的 ID 并通过 verify.py 的方法进行检测
不改动 verify.py 中的验证方法
"""

import sys
import os
import time
from pathlib import Path

# 添加当前目录到 Python 路径
sys.path.insert(0, str(Path(__file__).parent))

def test_single_id_with_verify():
    """测试单个自主生成的 ID"""
    print("🧪 测试单个自主生成的 ID")
    print("=" * 60)
    
    try:
        # 导入生成器和验证函数
        from xStatsigIDGenerator import XStatsigIDGenerator
        from verify import decrypt_statsig_id
        
        # 生成 ID
        print("🔧 生成 x-statsig-id...")
        generator = XStatsigIDGenerator()
        statsig_id = generator.generate_x_statsig_id()
        
        print(f"✅ 生成完成")
        print(f"   生成的ID: {statsig_id}")
        print(f"   ID长度: {len(statsig_id)} 字符")
        
        # 使用 verify.py 的方法进行验证
        print(f"\n🔍 使用 verify.py 进行验证...")
        result = decrypt_statsig_id(statsig_id)
        
        # 检查验证结果
        if result is None:
            print("❌ 验证失败：decrypt_statsig_id 返回 None")
            return False
        
        # 检查关键字段
        success = True
        checks = []
        
        # 检查异或key
        if 'xor_key' in result and result['xor_key'] is not None:
            checks.append(("异或key", True, f"0x{result['xor_key']:02x}"))
        else:
            checks.append(("异或key", False, "缺失"))
            success = False
        
        # 检查meta内容
        if 'meta_content' in result and result['meta_content'] is not None:
            meta = result['meta_content']
            if isinstance(meta, dict) and 'bytes' in meta and len(meta['bytes']) == 48:
                checks.append(("Meta内容", True, f"48字节"))
            else:
                checks.append(("Meta内容", False, "格式错误"))
                success = False
        else:
            checks.append(("Meta内容", False, "缺失"))
            success = False
        
        # 检查时间戳
        if 'timestamp' in result and result['timestamp'] is not None:
            ts = result['timestamp']
            if isinstance(ts, dict) and 'relative_seconds' in ts:
                checks.append(("时间戳", True, f"{ts['relative_seconds']}秒"))
            else:
                checks.append(("时间戳", False, "格式错误"))
                success = False
        else:
            checks.append(("时间戳", False, "缺失"))
            success = False
        
        # 检查SHA256片段
        if 'sha256_fragment' in result and result['sha256_fragment'] is not None:
            sha = result['sha256_fragment']
            if isinstance(sha, dict) and 'bytes' in sha and len(sha['bytes']) == 16:
                checks.append(("SHA256片段", True, f"16字节"))
            else:
                checks.append(("SHA256片段", False, "格式错误"))
                success = False
        else:
            checks.append(("SHA256片段", False, "缺失"))
            success = False
        
        # 检查固定值
        if 'fixed_value' in result and result['fixed_value'] == 3:
            checks.append(("固定值", True, "3"))
        else:
            checks.append(("固定值", False, f"{result.get('fixed_value', 'N/A')}"))
            success = False
        
        # 输出检查结果
        print(f"\n📊 验证结果检查:")
        for check_name, passed, value in checks:
            status = "✅" if passed else "❌"
            print(f"   {status} {check_name}: {value}")
        
        return success
        
    except Exception as e:
        print(f"❌ 测试异常: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_multiple_ids_with_verify():
    """测试多个自主生成的 ID"""
    print("\n🧪 测试多个自主生成的 ID")
    print("=" * 60)
    
    try:
        from xStatsigIDGenerator import XStatsigIDGenerator
        from verify import decrypt_statsig_id
        
        generator = XStatsigIDGenerator()
        test_count = 3
        results = []
        
        print(f"生成并验证 {test_count} 个 ID...")
        
        for i in range(test_count):
            print(f"\n--- 测试 ID #{i+1} ---")
            
            # 生成 ID
            statsig_id = generator.generate_x_statsig_id()
            print(f"生成的ID: {statsig_id[:50]}...")
            
            # 验证 ID
            result = decrypt_statsig_id(statsig_id)
            
            # 简化检查
            if result is None:
                success = False
                print("❌ 验证失败")
            else:
                # 检查关键字段是否存在且正确
                success = (
                    result.get('xor_key') is not None and
                    result.get('meta_content') is not None and
                    result.get('timestamp') is not None and
                    result.get('sha256_fragment') is not None and
                    result.get('fixed_value') == 3
                )
                print(f"{'✅' if success else '❌'} 验证{'通过' if success else '失败'}")
            
            results.append({
                'index': i + 1,
                'id': statsig_id,
                'success': success
            })
            
            # 短暂延迟
            time.sleep(0.1)
        
        # 统计结果
        success_count = sum(1 for r in results if r['success'])
        print(f"\n📊 批量测试结果:")
        print(f"   成功: {success_count}/{test_count}")
        print(f"   成功率: {success_count/test_count*100:.1f}%")
        
        return success_count == test_count
        
    except Exception as e:
        print(f"❌ 批量测试异常: {e}")
        return False

def test_different_parameters():
    """测试不同参数下的 ID 生成和验证"""
    print("\n🧪 测试不同参数下的 ID 生成和验证")
    print("=" * 60)
    
    try:
        from xStatsigIDGenerator import XStatsigIDGenerator
        from verify import decrypt_statsig_id
        
        generator = XStatsigIDGenerator()
        
        # 测试不同的参数组合
        test_cases = [
            ("GET", "/"),
            ("POST", "/api/chat"),
            ("GET", "/search"),
            ("PUT", "/update"),
            ("DELETE", "/delete")
        ]
        
        results = []
        
        for method, pathname in test_cases:
            print(f"\n--- 测试参数: {method} {pathname} ---")
            
            # 生成 ID
            statsig_id = generator.generate_x_statsig_id(method, pathname)
            print(f"生成的ID: {statsig_id[:50]}...")
            
            # 验证 ID
            result = decrypt_statsig_id(statsig_id)
            
            if result is None:
                success = False
                print("❌ 验证失败")
            else:
                # 检查固定值是否为3（最关键的验证）
                success = result.get('fixed_value') == 3
                print(f"{'✅' if success else '❌'} 验证{'通过' if success else '失败'}")
                
                if success:
                    print(f"   固定值: {result.get('fixed_value')}")
                    print(f"   异或key: 0x{result.get('xor_key', 0):02x}")
            
            results.append({
                'method': method,
                'pathname': pathname,
                'success': success
            })
        
        # 统计结果
        success_count = sum(1 for r in results if r['success'])
        print(f"\n📊 参数测试结果:")
        print(f"   成功: {success_count}/{len(test_cases)}")
        print(f"   成功率: {success_count/len(test_cases)*100:.1f}%")
        
        return success_count == len(test_cases)
        
    except Exception as e:
        print(f"❌ 参数测试异常: {e}")
        return False

def main():
    """主函数"""
    print("🚀 使用 verify.py 验证自主生成的 x-statsig-id")
    print("=" * 80)
    
    # 测试单个 ID
    single_success = test_single_id_with_verify()
    
    # 测试多个 ID
    multiple_success = test_multiple_ids_with_verify()
    
    # 测试不同参数
    param_success = test_different_parameters()
    
    # 总结
    print("\n" + "=" * 80)
    print("📋 最终测试总结")
    print("=" * 80)
    
    print(f"单个ID测试: {'✅ 通过' if single_success else '❌ 失败'}")
    print(f"多个ID测试: {'✅ 通过' if multiple_success else '❌ 失败'}")
    print(f"参数测试: {'✅ 通过' if param_success else '❌ 失败'}")
    
    overall_success = single_success and multiple_success and param_success
    
    if overall_success:
        print(f"\n🎉 所有测试通过！")
        print(f"✅ 自主生成的 x-statsig-id 完全通过 verify.py 验证")
        print(f"✅ 所有关键字段（异或key、Meta内容、时间戳、SHA256片段、固定值）都正确")
        print(f"✅ 不同参数下都能生成有效的 ID")
        print(f"✅ 生成器工作正常，可以放心使用")
    else:
        print(f"\n⚠️  部分测试失败")
        if not single_success:
            print(f"❌ 单个ID测试失败")
        if not multiple_success:
            print(f"❌ 多个ID测试失败")
        if not param_success:
            print(f"❌ 参数测试失败")
        print(f"❌ 需要检查生成器实现")
    
    print(f"\n📝 说明:")
    print(f"   - 本测试使用 verify.py 中的 decrypt_statsig_id 函数")
    print(f"   - 未修改 verify.py 中的任何验证逻辑")
    print(f"   - 验证了生成的 ID 的完整数据结构")
    print(f"   - 确保固定值为 3，这是最关键的验证点")
    
    return overall_success

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)