import base64
import struct
import hashlib
from datetime import datetime

def decrypt_statsig_id(statsig_id):
    """
    完整解密x-statsig-id

    数据结构:
    [1字节异或key] + [48字节meta content] + [4字节时间戳] + [16字节SHA256] + [1字节固定值3]
    """

    print("=" * 60)
    print("x-statsig-id 完整解密分析")
    print("=" * 60)

    # 1. Base64解码
    print(f"原始ID: {statsig_id}")
    print(f"长度: {len(statsig_id)} 字符")

    # 补齐padding
    padding = 4 - (len(statsig_id) % 4)
    if padding != 4:
        statsig_id += '=' * padding
        print(f"补齐padding后: {statsig_id}")

    try:
        decoded_bytes = base64.b64decode(statsig_id)
        print(f"Base64解码成功，长度: {len(decoded_bytes)} 字节")
    except Exception as e:
        print(f"Base64解码失败: {e}")
        return None

    # 2. 异或解密
    xor_key = decoded_bytes[0]
    print(f"\n异或key: 0x{xor_key:02x} ({xor_key})")

    decrypted = bytearray([xor_key])
    for i in range(1, len(decoded_bytes)):
        decrypted.append(decoded_bytes[i] ^ xor_key)

    print(f"异或解密后长度: {len(decrypted)} 字节")

    # 3. 解析数据结构
    result = {
        'xor_key': xor_key,
        'meta_content': None,
        'timestamp': None,
        'sha256_fragment': None,
        'fixed_value': None
    }

    offset = 1

    # Meta content (48字节)
    if offset + 48 <= len(decrypted):
        meta_bytes = decrypted[offset:offset+48]
        meta_b64 = base64.b64encode(meta_bytes).decode()
        result['meta_content'] = {
            'bytes': meta_bytes,
            'hex': meta_bytes.hex(),
            'base64': meta_b64
        }
        print(f"\n📋 Meta Content (48字节):")
        print(f"   Hex: {meta_bytes.hex()}")
        print(f"   Base64: {meta_b64}")
        offset += 48

    # 时间戳 (4字节)
    if offset + 4 <= len(decrypted):
        timestamp_bytes = decrypted[offset:offset+4]
        timestamp_le = struct.unpack('<I', timestamp_bytes)[0]

        base_timestamp = 1682924400  # 2023-05-01 00:00:00 UTC
        actual_timestamp = base_timestamp + timestamp_le

        result['timestamp'] = {
            'bytes': timestamp_bytes,
            'hex': timestamp_bytes.hex(),
            'relative_seconds': timestamp_le,
            'absolute_timestamp': actual_timestamp,
            'datetime': datetime.fromtimestamp(actual_timestamp)
        }

        print(f"\n⏰ 时间戳 (4字节):")
        print(f"   Hex: {timestamp_bytes.hex()}")
        print(f"   相对时间: {timestamp_le} 秒")
        print(f"   绝对时间: {datetime.fromtimestamp(actual_timestamp)}")
        offset += 4

    # SHA256片段 (16字节)
    if offset + 16 <= len(decrypted):
        hash_bytes = decrypted[offset:offset+16]
        result['sha256_fragment'] = {
            'bytes': hash_bytes,
            'hex': hash_bytes.hex()
        }

        print(f"\n🔐 SHA256片段 (16字节):")
        print(f"   Hex: {hash_bytes.hex()}")
        offset += 16

    # 固定值 (最后1字节)
    if len(decrypted) > 0:
        fixed_val = decrypted[-1]
        result['fixed_value'] = fixed_val

        print(f"\n🔒 固定值 (1字节): {fixed_val}")
        if fixed_val == 3:
            print("   ✅ 固定值正确 (期望值: 3)")
        else:
            print(f"   ❌ 固定值错误 (期望值: 3, 实际值: {fixed_val})")

    # 4. 验证和总结
    print(f"\n" + "=" * 60)
    print("解密总结")
    print("=" * 60)

    print(f"总数据长度: {len(decrypted)} 字节")
    print(f"数据结构验证:")
    print(f"  ✅ 异或key: 0x{xor_key:02x}")
    print(f"  ✅ Meta content: 48字节")
    print(f"  ✅ 时间戳: 4字节")
    print(f"  ✅ SHA256片段: 16字节")
    print(f"  ✅ 固定值: {fixed_val if 'fixed_val' in locals() else 'N/A'}")

    expected_length = 1 + 48 + 4 + 16 + 1
    print(f"  预期长度: {expected_length} 字节")
    print(f"  实际长度: {len(decrypted)} 字节")

    if expected_length == len(decrypted):
        print("  ✅ 长度验证通过")
    else:
        print("  ❌ 长度验证失败")

    return result