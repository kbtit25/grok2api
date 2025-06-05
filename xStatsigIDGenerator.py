#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import base64
import struct
import hashlib
import time
import secrets
import requests
import re
import json
from typing import Optional, Dict, Any

class XStatsigIDGenerator:
    """x-statsig-id 生成器"""
    
    def __init__(self):
        self.base_timestamp = int(time.time())  # 使用当前系统时间
        self.grok_url = "https://grok.com"
        
    def get_grok_meta_content(self) -> bytes:
        """
        从 grok.com 获取 meta 标签中的 grok-site-verification 内容
        
        Returns:
            48字节的meta内容
        """
        try:
            print("🌐 正在请求 grok.com...")
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
            }
            
            response = requests.get(self.grok_url, headers=headers, timeout=10)
            response.raise_for_status()
            
            html_content = response.text
            print(f"   HTML内容长度: {len(html_content)} 字符")
            
            # 查找 grok-site-verification meta 标签
            patterns = [
                r'<meta\s+name=["\']grok-site-verification["\']\s+content=["\']([^"\']+)["\']',
                r'<meta\s+content=["\']([^"\']+)["\']\s+name=["\']grok-site-verification["\']',
                r'grok-site-verification["\']?\s*(?:content|value)\s*=\s*["\']([^"\']+)["\']'
            ]
            
            verification_content = None
            for pattern in patterns:
                match = re.search(pattern, html_content, re.IGNORECASE)
                if match:
                    verification_content = match.group(1)
                    print(f"   找到 grok-site-verification: {verification_content[:50]}...")
                    break
            
            if not verification_content:
                print("   ⚠️  未找到 grok-site-verification，使用默认内容")
                verification_content = "default-grok-verification-content-for-fallback-use"
            
            # 转换为48字节
            meta_bytes = verification_content.encode('utf-8')
            if len(meta_bytes) < 48:
                meta_bytes = meta_bytes + b'\x00' * (48 - len(meta_bytes))
            elif len(meta_bytes) > 48:
                meta_bytes = meta_bytes[:48]
                
            print(f"   Meta内容 (48字节): {meta_bytes.hex()[:32]}...")
            return meta_bytes
            
        except Exception as e:
            print(f"   ❌ 获取grok meta失败: {e}")
            print("   使用备用meta内容")
            fallback = b"backup-grok-meta-content-when-request-fails-ok"
            return fallback + b'\x00' * (48 - len(fallback))
    
    def generate_browser_fingerprint(self) -> str:
        """
        生成浏览器指纹信息 (结合方法1和方法3)
        
        Returns:
            指纹字符串
        """
        print("🔍 生成浏览器指纹...")
        
        # 模拟浏览器指纹信息
        fingerprint_data = {
            "userAgent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36",
            "language": "en",
            "languages": ["en", "zh", "zh-TW", "zh-CN"],
            "platform": "MacIntel",
            "cookieEnabled": True,
            "doNotTrack": None,
            "screenWidth": 450,
            "screenHeight": 654,
            "screenColorDepth": 24,
            "screenPixelDepth": 24,
            "screenAvailWidth": 450,
            "screenAvailHeight": 654,
            "innerWidth": 450,
            "innerHeight": 654,
            "outerWidth": 1920,
            "outerHeight": 1055,
            "timezone": "Asia/Shanghai",
            "timezoneOffset": -480,
            "hardwareConcurrency": 14,
            "deviceMemory": 8,
            "maxTouchPoints": 0
        }
        
        # 方法3: 生成指纹哈希
        fingerprint_string = json.dumps(fingerprint_data, sort_keys=True, separators=(',', ':'))
        fingerprint_hash = hashlib.sha256(fingerprint_string.encode('utf-8')).hexdigest()
        
        print(f"   指纹数据长度: {len(fingerprint_string)} 字符")
        print(f"   指纹哈希: {fingerprint_hash[:32]}...")
        
        return fingerprint_hash
    
    def generate_x_statsig_id(self, method: str = "GET", pathname: str = "/") -> str:
        """
        生成完整的 x-statsig-id
        
        Args:
            method: 请求方式 (GET/POST)
            pathname: 请求路径
        
        Returns:
            生成的 x-statsig-id 字符串
        """
        print("=" * 60)
        print("🚀 开始生成 x-statsig-id")
        print("=" * 60)
        
        print(f"📋 生成参数:")
        print(f"   Method: {method}")
        print(f"   Pathname: {pathname}")
        
        # 1. 获取 grok.com 的 meta content
        meta_content = self.get_grok_meta_content()
        
        # 2. 生成浏览器指纹
        fingerprint = self.generate_browser_fingerprint()
        
        # 3. 生成当前时间戳
        current_timestamp = int(time.time())
        relative_timestamp = current_timestamp - self.base_timestamp
        
        print(f"⏰ 时间信息:")
        print(f"   当前时间戳: {current_timestamp}")
        print(f"   基准时间戳: {self.base_timestamp}")
        print(f"   相对时间戳: {relative_timestamp}")
        
        # 4. 生成时间戳字节 (小端序)
        timestamp_bytes = struct.pack('<I', relative_timestamp)
        print(f"   时间戳字节: {timestamp_bytes.hex()}")
        
        # 5. 生成SHA256
        sha_input = f"{method}!{pathname}!{relative_timestamp}{fingerprint}"
        sha256_hash = hashlib.sha256(sha_input.encode('utf-8')).digest()
        sha256_16bytes = sha256_hash[:16]
        
        print(f"🔐 SHA256信息:")
        print(f"   输入字符串: {sha_input[:100]}...")
        print(f"   SHA256前16字节: {sha256_16bytes.hex()}")
        
        # 6. 固定值
        fixed_byte = b'\x03'
        
        # 7. 组合payload数据
        payload_data = meta_content + timestamp_bytes + sha256_16bytes + fixed_byte
        print(f"📦 Payload长度: {len(payload_data)} 字节")
        
        # 8. 生成异或key并加密
        xor_key = secrets.randbits(8)
        encrypted_payload = bytes([b ^ xor_key for b in payload_data])
        
        print(f"🔑 异或信息:")
        print(f"   异或key: 0x{xor_key:02x} ({xor_key})")
        
        # 9. 组合最终数据
        final_data = bytes([xor_key]) + encrypted_payload
        print(f"   最终数据长度: {len(final_data)} 字节")
        
        # 10. Base64编码
        result = base64.b64encode(final_data).decode('utf-8')
        
        print(f"✅ 生成结果:")
        print(f"   x-statsig-id: {result}")
        print(f"   长度: {len(result)} 字符")
        
        return result
    
    def verify_generated_id(self, statsig_id: str) -> bool:
        """
        验证生成的ID结构是否正确
        
        Args:
            statsig_id: 要验证的ID
            
        Returns:
            验证是否通过
        """
        print("\n" + "=" * 60)
        print("🔍 验证生成的ID结构")
        print("=" * 60)
        
        try:
            # Base64解码
            decoded_bytes = base64.b64decode(statsig_id)
            print(f"✅ Base64解码成功，长度: {len(decoded_bytes)} 字节")
            
            # 提取异或key
            xor_key = decoded_bytes[0]
            print(f"✅ 异或key: 0x{xor_key:02x} ({xor_key})")
            
            # 异或解密
            decrypted = bytearray()
            for i in range(1, len(decoded_bytes)):
                decrypted.append(decoded_bytes[i] ^ xor_key)
            
            print(f"✅ 解密后长度: {len(decrypted)} 字节")
            
            # 验证数据结构
            expected_length = 48 + 4 + 16 + 1  # meta + timestamp + sha256 + fixed
            if len(decrypted) == expected_length:
                print(f"✅ 数据长度正确: {len(decrypted)}/{expected_length}")
            else:
                print(f"❌ 数据长度错误: {len(decrypted)}/{expected_length}")
                return False
            
            # 检查固定值
            fixed_val = decrypted[-1]
            if fixed_val == 3:
                print(f"✅ 固定值正确: {fixed_val}")
            else:
                print(f"❌ 固定值错误: {fixed_val} (期望: 3)")
                return False
            
            # 解析时间戳
            timestamp_bytes = decrypted[48:52]
            timestamp = struct.unpack('<I', timestamp_bytes)[0]
            actual_time = self.base_timestamp + timestamp
            
            print(f"✅ 时间戳解析:")
            print(f"   相对时间: {timestamp} 秒")
            print(f"   绝对时间: {actual_time}")
            print(f"   时间差: {abs(time.time() - actual_time):.1f} 秒")
            
            print("🎉 ID结构验证通过！")
            return True
            
        except Exception as e:
            print(f"❌ 验证失败: {e}")
            return False

def main():
    """主函数 - 演示完整流程"""
    generator = XStatsigIDGenerator()
    
    # 生成 x-statsig-id
    method = "GET"
    pathname = "/"
    
    statsig_id = generator.generate_x_statsig_id(method, pathname)
    
    # 验证生成的ID
    generator.verify_generated_id(statsig_id)
    
    print(f"\n" + "=" * 60)
    print("📋 使用说明")
    print("=" * 60)
    print("在HTTP请求中使用:")
    print(f"Headers: {{'x-statsig-id': '{statsig_id}'}}")

if __name__ == "__main__":
    main()
