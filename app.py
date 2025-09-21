import os
import json
import uuid
import time
import threading
import queue
import base64
import sys
import inspect
import secrets
import re
from loguru import logger
from pathlib import Path
import uuid
import requests
from flask import Flask, request, Response, jsonify, stream_with_context, render_template, redirect, session
from curl_cffi import requests as curl_requests
from werkzeug.middleware.proxy_fix import ProxyFix
from xStatsigIDGenerator import XStatsigIDGenerator
import random
import string

CORE_WORDS = [
    '__value', '_data-enctype', '_data-margin', '_style', '_transform', '_value',
    'className', 'color', 'currentTime', 'dataset', 'disabled', 'enctype',
    'href', 'innerHTML', 'method', 'multiple', 'name', 'naturalHeight',
    'naturalWidth', 'offsetWidth', 'onclick', 'onerror', 'options', 'padding',
    'paused', 'placeholder', 'position', 'scrollLeft', 'title', 'transform',
    'type', 'width', 'zIndex', 'volume'
]
MODIFIERS = [
    'InnerHTML', 'Children', 'Style', 'Options', 'Disabled', 'Onload', 'Volume', 'Alt'
]

def generate_random_part(length_min=4, length_max=8):
    """生成一段随机乱码"""
    length = random.randint(length_min, length_max)
    return ''.join(random.choices('abcdefghijklmnopqrstuvwxyz0123456789', k=length))

def create_error_filler():
    """根据配方，随机组合出一个报错填充物"""
    roll = random.random()

    if roll < 0.40: # 40% 的概率: 核心词 + 随机后缀
        word = random.choice(CORE_WORDS)
        suffix = generate_random_part(4, 4)
        return f"{word}_{suffix}"
    elif roll < 0.65: # 25% 的概率: 纯核心词
        return random.choice(CORE_WORDS)
    elif roll < 0.85: # 20% 的概率: 纯随机乱码
        return generate_random_part(8, 12)
    elif roll < 0.95: # 10% 的概率: 核心词 + 数组/索引访问
        word = random.choice(CORE_WORDS)
        if random.random() < 0.5:
            index = random.randint(0, 2)
            return f"{word}[{index}]"
        else:
            index = generate_random_part(4, 4)
            return f"{word}['{index}']"
    else: # 5% 的概率: 核心词 + 修饰词
        word1 = random.choice(CORE_WORDS).capitalize()
        word2 = random.choice(MODIFIERS)
        return f"{word1.lower()}{word2}"

def generate_fallback_id():
    """
    在本地生成一个模拟的、可接受的“错误回退”x-statsig-id。
    这是 soundai.ee 接口的本地化实现。
    """
    error_filler = create_error_filler()
    error_template = "e:TypeError: Cannot read properties of null (reading '{filler}')"
    error_message = error_template.format(filler=error_filler)
    fallback_id = base64.b64encode(error_message.encode('utf-8')).decode('utf-8')
    return fallback_id

class Logger:
    def __init__(self, level="INFO", colorize=True, format=None):
        logger.remove()

        if format is None:
            format = (
                "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
                "<level>{level: <8}</level> | "
                "<cyan>{extra[filename]}</cyan>:<cyan>{extra[function]}</cyan>:<cyan>{extra[lineno]}</cyan> | "
                "<level>{message}</level>"
            )

        logger.add(
            sys.stderr,
            level=level,
            format=format,
            colorize=colorize,
            backtrace=True,
            diagnose=True
        )

        self.logger = logger

    def _get_caller_info(self):
        frame = inspect.currentframe()
        try:
            caller_frame = frame.f_back.f_back
            full_path = caller_frame.f_code.co_filename
            function = caller_frame.f_code.co_name
            lineno = caller_frame.f_lineno

            filename = os.path.basename(full_path)

            return {
                'filename': filename,
                'function': function,
                'lineno': lineno
            }
        finally:
            del frame

    def info(self, message, source="API"):
        caller_info = self._get_caller_info()
        self.logger.bind(**caller_info).info(f"[{source}] {message}")

    def error(self, message, source="API"):
        caller_info = self._get_caller_info()

        if isinstance(message, Exception):
            self.logger.bind(**caller_info).exception(f"[{source}] {str(message)}")
        else:
            self.logger.bind(**caller_info).error(f"[{source}] {message}")

    def warning(self, message, source="API"):
        caller_info = self._get_caller_info()
        self.logger.bind(**caller_info).warning(f"[{source}] {message}")

    def debug(self, message, source="API"):
        caller_info = self._get_caller_info()
        self.logger.bind(**caller_info).debug(f"[{source}] {message}")

    async def request_logger(self, request):
        caller_info = self._get_caller_info()
        self.logger.bind(**caller_info).info(f"请求: {request.method} {request.path}", "Request")

logger = Logger(level="INFO")
DATA_DIR = Path("/data")

if not DATA_DIR.exists():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
CONFIG = {
    "MODELS": {
        'grok-4-heavy': 'grok-4-heavy',
        'grok-4': 'grok-4',
        'grok-4-imageGen': 'grok-4',
        #'grok-4-fast': 'grok-4',
        #'grok-4-search': 'grok-4',
        "grok-3": "grok-3",
        #"grok-3-search": "grok-3",
        "grok-3-imageGen": "grok-3",
        "grok-4-mini-thinking-tahoe": "grok-4-mini-thinking-tahoe",
        #"grok-3-deepersearch": "grok-3",
        #"grok-3-reasoning": "grok-3"
    },
    "API": {
        "IS_TEMP_CONVERSATION": os.environ.get("IS_TEMP_CONVERSATION", "true").lower() == "true",
        "IS_CUSTOM_SSO": os.environ.get("IS_CUSTOM_SSO", "false").lower() == "true",
        "BASE_URL": "https://grok.com",
        "API_KEY": os.environ.get("API_KEY", "sk-123456"),
        "SIGNATURE_COOKIE": None,
        "PICGO_KEY": os.environ.get("PICGO_KEY") or None,
        "TUMY_KEY": os.environ.get("TUMY_KEY") or None,
        "RETRY_TIME": 1000,
        "PROXY": os.environ.get("PROXY") or None
    },
    "ADMIN": {
        "MANAGER_SWITCH": os.environ.get("MANAGER_SWITCH") or None,
        "PASSWORD": os.environ.get("ADMINPASSWORD") or None 
    },
    "SERVER": {
        "COOKIE": None,
        "CF_CLEARANCE":os.environ.get("CF_CLEARANCE") or None,
        "PORT": int(os.environ.get("PORT", 5200))
    },
    "RETRY": {
        "RETRYSWITCH": False,
        "MAX_ATTEMPTS": 2
    },
    "TOKEN_STATUS_FILE": str(DATA_DIR / "token_status.json"),
    "SHOW_THINKING": os.environ.get("SHOW_THINKING") == "true",
    "IS_THINKING": False,
    "IS_IMG_GEN": False,
    "IS_IMG_GEN2": False,
    "ISSHOW_SEARCH_RESULTS": os.environ.get("ISSHOW_SEARCH_RESULTS", "true").lower() == "true"
}

def generate_statsig_id_fallback():
    """
    使用自主生成方法作为备用方案生成 x_statsig_id
    """
    try:
        generator = XStatsigIDGenerator()
        x_statsig_id = generator.generate_x_statsig_id()
        logger.info("使用自主生成方法成功生成 x_statsig_id", "StatsigGenerator")
        return x_statsig_id
    except Exception as e:
        logger.error(f"自主生成 x_statsig_id 失败: {e}", "StatsigGenerator")
        # 如果自主生成也失败，返回一个默认值
        return "fallback-statsig-id-" + str(uuid.uuid4())

def get_x_statsig_id_primary():
    """
    主要策略：优先使用自主生成方法生成 x_statsig_id
    """
    try:
        logger.info("使用主要策略：自主生成 x_statsig_id", "StatsigGenerator")
        generator = XStatsigIDGenerator()
        x_statsig_id = generator.generate_x_statsig_id()
        logger.info("主要策略成功：自主生成 x_statsig_id 完成", "StatsigGenerator")
        return {
            'success': True,
            'x_statsig_id': x_statsig_id,
            'method': 'self_generated'
        }
    except Exception as e:
        logger.error(f"主要策略失败：自主生成 x_statsig_id 错误: {e}", "StatsigGenerator")
        return {
            'success': False,
            'error': str(e),
            'method': 'self_generated'
        }

def get_x_statsig_id_fallback():
    """
    备用策略：使用本地生成的“错误回退ID”，替代原来的网络请求。
    """
    try:
        logger.info("使用备用策略：本地生成错误回退 ID", "StatsigLocal")
        fallback_id = generate_fallback_id()
        
        if fallback_id:
            logger.info("备用策略成功：本地生成错误回退 ID 完成", "StatsigLocal")
            return {
                'success': True,
                'x_statsig_id': fallback_id,
                'method': 'local_fallback_generator'
            }
        else:
            # 理论上我们自己的代码不会失败，但还是保留错误处理
            logger.error("备用策略失败：本地生成ID时出错", "StatsigLocal")
            return {
                'success': False,
                'error': '本地生成ID失败',
                'method': 'local_fallback_generator'
            }

    except Exception as e:
        logger.error(f"备用策略异常：{e}", "StatsigLocal")
        return {
            'success': False,
            'error': str(e),
            'method': 'local_fallback_generator'
        }

def get_x_statsig_id():
    """
    获取 x_statsig_id，优先使用自主生成方法，失败时使用 PHP 接口
    """
    # 主要策略：自主生成
    primary_result = get_x_statsig_id_primary()

    if primary_result['success']:
        return primary_result['x_statsig_id']

    # 备用策略：PHP 接口
    logger.warning("主要策略失败，切换到备用策略", "StatsigStrategy")
    fallback_result = get_x_statsig_id_fallback()

    if fallback_result['success']:
        return fallback_result['x_statsig_id']

    # 所有策略都失败，返回默认值
    logger.error("所有策略都失败，使用默认 x_statsig_id", "StatsigStrategy")
    return "fallback-statsig-id-" + str(uuid.uuid4())

# 初始化 x_statsig_id（在应用启动时获取一次）
_cached_x_statsig_id = None
_cached_x_statsig_id_method = None

def get_cached_x_statsig_id():
    """
    获取缓存的 x_statsig_id，如果没有缓存则重新获取
    """
    global _cached_x_statsig_id, _cached_x_statsig_id_method
    if _cached_x_statsig_id is None:
        _cached_x_statsig_id = get_x_statsig_id()
        _cached_x_statsig_id_method = 'initial'
    return _cached_x_statsig_id

def refresh_x_statsig_id_with_fallback():
    """
    强制刷新 x_statsig_id，使用备用策略（PHP 接口）
    """
    global _cached_x_statsig_id, _cached_x_statsig_id_method

    logger.info("强制刷新 x_statsig_id，使用备用策略", "StatsigStrategy")
    fallback_result = get_x_statsig_id_fallback()

    if fallback_result['success']:
        _cached_x_statsig_id = fallback_result['x_statsig_id']
        _cached_x_statsig_id_method = 'php_interface'
        logger.info("成功使用备用策略刷新 x_statsig_id", "StatsigStrategy")
        return _cached_x_statsig_id
    else:
        logger.error("备用策略也失败，保持原有 x_statsig_id", "StatsigStrategy")
        return _cached_x_statsig_id

def get_default_headers(force_refresh_statsig=False):
    """
    动态生成默认请求头，确保 X-Statsig-Id 总是可用

    Args:
        force_refresh_statsig: 是否强制刷新 x_statsig_id（使用备用策略）
    """
    if force_refresh_statsig:
        statsig_id = refresh_x_statsig_id_with_fallback()
    else:
        statsig_id = get_cached_x_statsig_id()

    return {
        'Accept': '*/*',
        'Accept-Language': 'zh-CN,zh;q=0.9',
        'Accept-Encoding': 'gzip, deflate, br, zstd',
        'Content-Type': 'text/plain;charset=UTF-8',
        'Connection': 'keep-alive',
        'Origin': 'https://grok.com',
        'Priority': 'u=1, i',
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/137.0.0.0 Safari/537.36',
        'Sec-Ch-Ua': '"Not(A:Brand";v="99", "Google Chrome";v="133", "Chromium";v="133"',
        'Sec-Ch-Ua-Mobile': '?0',
        'Sec-Ch-Ua-Platform': '"macOS"',
        'Sec-Fetch-Dest': 'empty',
        'Sec-Fetch-Mode': 'cors',
        'Sec-Fetch-Site': 'same-origin',
        'X-Statsig-Id': statsig_id,
        'X-Xai-Request-Id': str(uuid.uuid4()),
        'Baggage': 'sentry-public_key=b311e0f2690c81f25e2c4cf6d4f7ce1c'
    }

# 为了向后兼容，保留 DEFAULT_HEADERS 变量
DEFAULT_HEADERS = get_default_headers()

# 替换你现有的 AuthTokenManager 类
class AuthTokenManager:
    def __init__(self):
        self.token_model_map = {}
        self.expired_tokens = set()
        self.token_status_map = {}
        
        # 1. 定义不同等级的配置
        # 普通账号配置 (你可以根据需要调整)
        self.model_normal_config = {
            "grok-4":              { "RequestFrequency": 20, "ExpirationTime": 24 * 60 * 60 * 1000 },
            "grok-3":              { "RequestFrequency": 30, "ExpirationTime": 2 * 60 * 60 * 1000 },
            "grok-4-mini-thinking-tahoe":         { "RequestFrequency": 1000,  "ExpirationTime": 24 * 60 * 60 * 1000 },
            #"grok-3-deepersearch": { "RequestFrequency": 5, "ExpirationTime": 24 * 60 * 60 * 1000 },
            #"grok-3-reasoning":    { "RequestFrequency": 8, "ExpirationTime": 24 * 60 * 60 * 1000 }
        }
        
        # Heavy 账号配置 (你可以根据需要调整)
        self.model_heavy_config = {
            # Heavy 账号可以访问所有普通模型，且次数更多
            "grok-4":              { "RequestFrequency": 100, "ExpirationTime": 24 * 60 * 60 * 1000 },
            "grok-3":              { "RequestFrequency": 150, "ExpirationTime": 2 * 60 * 60 * 1000 },
            #"grok-3-deepsearch":   { "RequestFrequency": 50,  "ExpirationTime": 24 * 60 * 60 * 1000 },
            #"grok-3-deepersearch": { "RequestFrequency": 25,  "ExpirationTime": 24 * 60 * 60 * 1000 },
            "grok-4-mini-thinking-tahoe":         { "RequestFrequency": 1000,  "ExpirationTime": 24 * 60 * 60 * 1000 },
            # 只有 Heavy 账号可以访问 heavy 模型
            "grok-4-heavy":        { "RequestFrequency": 20,  "ExpirationTime": 24 * 60 * 60 * 1000 }
        }

        self.token_reset_switch = False
        self.token_reset_timer = None
        self.load_token_status()


    def save_token_status(self):
        try:        
            with open(CONFIG["TOKEN_STATUS_FILE"], 'w', encoding='utf-8') as f:
                json.dump(self.token_status_map, f, indent=2, ensure_ascii=False)
            logger.info("令牌状态已保存到配置文件", "TokenManager")
        except Exception as error:
            logger.error(f"保存令牌状态失败: {str(error)}", "TokenManager")
            
    def load_token_status(self):
        try:
            token_status_file = Path(CONFIG["TOKEN_STATUS_FILE"])
            if token_status_file.exists():
                with open(token_status_file, 'r', encoding='utf-8') as f:
                    self.token_status_map = json.load(f)
                logger.info("已从配置文件加载令牌状态", "TokenManager")
        except Exception as error:
            logger.error(f"加载令牌状态失败: {str(error)}", "TokenManager")
    
    # 修改 add_token 以支持分组
    def add_token(self, token, token_type="normal", isinitialization=False):
        sso = token.split("sso=")[1].split(";")[0]
        
        config_to_use = self.model_heavy_config if token_type == "heavy" else self.model_normal_config
        models_to_add = config_to_use.keys()

        for model in models_to_add:
            if model not in self.token_model_map:
                self.token_model_map[model] = []
            if sso not in self.token_status_map:
                self.token_status_map[sso] = {}

            if any(entry["token"] == token for entry in self.token_model_map[model]):
                continue

            self.token_model_map[model].append({
                "token": token,
                "RequestCount": 0,
                "AddedTime": int(time.time() * 1000),
                "StartCallTime": None,
                "type": token_type
            })

            if model not in self.token_status_map[sso]:
                self.token_status_map[sso][model] = {
                    "isValid": True,
                    "invalidatedTime": None,
                    "totalRequestCount": 0,
                    "type": token_type
                }
        if not isinitialization:
            self.save_token_status()

    # set_token 也需要适应分组逻辑 (虽然 chat_completions 没用，但保持完整)
    def set_token(self, token, token_type="normal"):
        config_to_use = self.model_heavy_config if token_type == "heavy" else self.model_normal_config
        models = list(config_to_use.keys())
        
        self.token_model_map = {model: [{
            "token": token,
            "RequestCount": 0,
            "AddedTime": int(time.time() * 1000),
            "StartCallTime": None,
            "type": token_type
        }] for model in models}

        sso = token.split("sso=")[1].split(";")[0]
        self.token_status_map[sso] = {model: {
            "isValid": True,
            "invalidatedTime": None,
            "totalRequestCount": 0,
            "type": token_type
        } for model in models}

    def delete_token(self, token):
        try:
            sso = token.split("sso=")[1].split(";")[0]
            for model in self.token_model_map:
                self.token_model_map[model] = [entry for entry in self.token_model_map[model] if entry["token"] != token]

            if sso in self.token_status_map:
                del self.token_status_map[sso]
            
            self.save_token_status()
            logger.info(f"令牌已成功移除: {token}", "TokenManager")
            return True
        except Exception as error:
            logger.error(f"令牌删除失败: {str(error)}")
            return False

    def reduce_token_request_count(self, model_id, count):
        try:
            normalized_model = self.normalize_model_name(model_id)
            if normalized_model not in self.token_model_map or not self.token_model_map[normalized_model]:
                return False
                
            token_entry = self.token_model_map[normalized_model][0]
            new_count = max(0, token_entry["RequestCount"] - count)
            reduction = token_entry["RequestCount"] - new_count
            token_entry["RequestCount"] = new_count
            
            if token_entry["token"]:
                sso = token_entry["token"].split("sso=")[1].split(";")[0]
                if sso in self.token_status_map and normalized_model in self.token_status_map[sso]:
                    self.token_status_map[sso][normalized_model]["totalRequestCount"] = max(
                        0, self.token_status_map[sso][normalized_model]["totalRequestCount"] - reduction)
            return True
        except Exception as error:
            logger.error(f"重置校对token请求次数时发生错误: {str(error)}", "TokenManager")
            return False

    def get_next_token_for_model(self, model_id, is_return=False):
        normalized_model = self.normalize_model_name(model_id)

        if normalized_model not in self.token_model_map or not self.token_model_map[normalized_model]:
            return None

        token_entry = self.token_model_map[normalized_model][0]
        
        if is_return:
            return token_entry["token"]

        config_to_use = self.model_heavy_config if token_entry.get("type") == "heavy" else self.model_normal_config
        
        if normalized_model not in config_to_use:
            logger.error(f"模型 {normalized_model} 不在类型为 '{token_entry.get('type')}' 的配置中", "TokenManager")
            self.remove_token_from_model(normalized_model, token_entry["token"])
            return self.get_next_token_for_model(model_id, is_return)

        model_config = config_to_use[normalized_model]
        
        if token_entry.get("StartCallTime") is None:
            token_entry["StartCallTime"] = int(time.time() * 1000)

        if not self.token_reset_switch:
            self.start_token_reset_process()
            self.token_reset_switch = True

        token_entry["RequestCount"] += 1

        if token_entry["RequestCount"] > model_config["RequestFrequency"]:
            self.remove_token_from_model(normalized_model, token_entry["token"])
            next_list = self.token_model_map.get(normalized_model, [])
            return next_list[0]["token"] if next_list else None

        sso = token_entry["token"].split("sso=")[1].split(";")[0]
        if sso in self.token_status_map and normalized_model in self.token_status_map[sso]:
            self.token_status_map[sso][normalized_model]["totalRequestCount"] += 1
            if token_entry["RequestCount"] >= model_config["RequestFrequency"]:
                 self.token_status_map[sso][normalized_model]["isValid"] = False
                 self.token_status_map[sso][normalized_model]["invalidatedTime"] = int(time.time() * 1000)
        
        self.save_token_status()
        return token_entry["token"]

    def remove_token_from_model(self, model_id, token):
        normalized_model = self.normalize_model_name(model_id)
        if normalized_model not in self.token_model_map: return False

        model_tokens = self.token_model_map[normalized_model]
        token_index = -1
        for i, entry in enumerate(model_tokens):
            if entry["token"] == token:
                token_index = i
                break
        
        if token_index != -1:
            removed_entry = model_tokens.pop(token_index)
            self.expired_tokens.add(
                (removed_entry["token"], normalized_model, int(time.time() * 1000), removed_entry.get("type", "normal"))
            )
            logger.info(f"模型 {model_id} 的令牌 {token} 已失效并移入冷却池。", "TokenManager")
            return True
        return False

    def get_expired_tokens(self):
        return list(self.expired_tokens)

    # --- 以下是你版本中独有的、必须保留的辅助方法 ---
    def normalize_model_name(self, model):
        # grok-4-heavy 必须被正确处理，不能被 normalize 成 grok-4
        if model in {'grok-4-heavy', 'grok-4-mini-thinking-tahoe'}:
            return model
        if model.startswith('grok-') and 'deepsearch' not in model and 'reasoning' not in model:
            return '-'.join(model.split('-')[:2])
        return model

    def get_token_count_for_model(self, model_id):
        normalized_model = self.normalize_model_name(model_id)
        return len(self.token_model_map.get(normalized_model, []))

    def get_remaining_token_request_capacity(self):
        remaining_capacity_map = {}
        all_configs = {**self.model_normal_config, **self.model_heavy_config}
        
        for model in all_configs.keys():
            model_tokens = self.token_model_map.get(model, [])
            if not model_tokens:
                remaining_capacity_map[model] = 0
                continue
                
            total_capacity = 0
            for entry in model_tokens:
                config_to_use = self.model_heavy_config if entry.get("type") == "heavy" else self.model_normal_config
                if model in config_to_use:
                    total_capacity += config_to_use[model]["RequestFrequency"]
            
            total_used_requests = sum(entry.get("RequestCount", 0) for entry in model_tokens)
            remaining_capacity_map[model] = max(0, total_capacity - total_used_requests)
            
        return remaining_capacity_map

    def get_token_array_for_model(self, model_id):
        normalized_model = self.normalize_model_name(model_id)
        return self.token_model_map.get(normalized_model, [])

    def start_token_reset_process(self):
        def reset_expired_tokens():
            now = int(time.time() * 1000)
            tokens_to_remove = set()
            
            for token_info in self.expired_tokens:
                token, model, expired_time, token_type = token_info
                
                config_to_use = self.model_heavy_config if token_type == "heavy" else self.model_normal_config
                if model not in config_to_use: continue
                
                expiration_time = config_to_use[model]["ExpirationTime"]

                if now - expired_time >= expiration_time:
                    if model not in self.token_model_map: self.token_model_map[model] = []
                    if not any(e["token"] == token for e in self.token_model_map[model]):
                        self.token_model_map[model].append({
                            "token": token, "RequestCount": 0, "AddedTime": now,
                            "StartCallTime": None, "type": token_type
                        })

                    sso = token.split("sso=")[1].split(";")[0]
                    if sso in self.token_status_map and model in self.token_status_map[sso]:
                        self.token_status_map[sso][model]["isValid"] = True
                        self.token_status_map[sso][model]["invalidatedTime"] = None
                        self.token_status_map[sso][model]["totalRequestCount"] = 0
                    
                    tokens_to_remove.add(token_info)

            self.expired_tokens -= tokens_to_remove

            all_configs = {**self.model_normal_config, **self.model_heavy_config}
            for model, tokens in self.token_model_map.items():
                if model not in all_configs: continue
                expiration_time = all_configs[model]["ExpirationTime"]
                for entry in tokens:
                    if entry.get("StartCallTime") and now - entry["StartCallTime"] >= expiration_time:
                        entry["RequestCount"] = 0
                        entry["StartCallTime"] = None
                        sso = entry["token"].split("sso=")[1].split(";")[0]
                        if sso in self.token_status_map and model in self.token_status_map[sso]:
                           self.token_status_map[sso][model]["isValid"] = True
                           self.token_status_map[sso][model]["invalidatedTime"] = None
                           self.token_status_map[sso][model]["totalRequestCount"] = 0

        import threading
        def run_timer():
            while True:
                reset_expired_tokens()
                time.sleep(3600)
        timer_thread = threading.Thread(target=run_timer, daemon=True)
        timer_thread.start()

    def get_all_tokens(self):
        all_tokens = set()
        for model_tokens in self.token_model_map.values():
            for entry in model_tokens:
                all_tokens.add(entry["token"])
        return list(all_tokens)

    def get_current_token(self, model_id):
        normalized_model = self.normalize_model_name(model_id)
        if normalized_model not in self.token_model_map or not self.token_model_map[normalized_model]:
            return None
        return self.token_model_map[normalized_model][0]["token"]

    def get_token_status_map(self):
        return self.token_status_map



def smart_grok_request_with_fallback(request_func, *args, **kwargs):
    """
    智能 Grok API 请求函数，支持 x_statsig_id 降级重试机制

    Args:
        request_func: 要执行的请求函数
        *args: 请求函数的位置参数
        **kwargs: 请求函数的关键字参数

    Returns:
        请求结果
    """
    max_retries = 2  # 最多重试2次（主要策略1次 + 备用策略1次）

    for attempt in range(max_retries):
        try:
            # 第一次尝试使用当前的 x_statsig_id（可能是自主生成的）
            if attempt == 0:
                logger.info("使用主要策略发起 Grok API 请求", "SmartRequest")
                response = request_func(*args, **kwargs)
            else:
                # 第二次尝试：强制使用备用策略（PHP 接口）刷新 x_statsig_id
                logger.warning("主要策略失败，使用备用策略重新发起 Grok API 请求", "SmartRequest")

                # 更新 kwargs 中的 headers，强制刷新 x_statsig_id
                if 'headers' in kwargs:
                    kwargs['headers'].update(get_default_headers(force_refresh_statsig=True))
                else:
                    kwargs['headers'] = get_default_headers(force_refresh_statsig=True)

                response = request_func(*args, **kwargs)

            # 检查响应状态码
            if hasattr(response, 'status_code'):
                status_code = response.status_code

                # 如果是成功状态码，直接返回
                if 200 <= status_code < 300:
                    if attempt > 0:
                        logger.info(f"备用策略成功：Grok API 请求成功 (状态码: {status_code})", "SmartRequest")
                    else:
                        logger.info(f"主要策略成功：Grok API 请求成功 (状态码: {status_code})", "SmartRequest")
                    return response

                # 如果是 4xx 或 5xx 错误，且还有重试机会，继续重试
                elif (400 <= status_code < 600) and attempt < max_retries - 1:
                    logger.warning(f"Grok API 请求失败 (状态码: {status_code})，尝试使用备用策略", "SmartRequest")
                    continue
                else:
                    # 最后一次重试也失败了
                    logger.error(f"所有策略都失败：Grok API 请求失败 (状态码: {status_code})", "SmartRequest")
                    return response
            else:
                # 没有 status_code 属性，直接返回响应
                return response

        except Exception as e:
            if attempt < max_retries - 1:
                logger.warning(f"Grok API 请求异常: {e}，尝试使用备用策略", "SmartRequest")
                continue
            else:
                logger.error(f"所有策略都失败：Grok API 请求异常: {e}", "SmartRequest")
                raise

    # 理论上不会到达这里
    return None

class Utils:
    # 1. 使用 threading.local() 来创建线程安全的存储
    _local = threading.local()

    @staticmethod
    def reset_citation_counter():
        """为当前线程初始化或重置计数器"""
        Utils._local.citation_counter = 1

    @staticmethod
    def get_citation_counter():
        """获取当前线程的计数器值"""
        # 如果当前线程还没有计数器，就初始化一个
        if not hasattr(Utils._local, 'citation_counter'):
            Utils._local.citation_counter = 1
        return Utils._local.citation_counter

    @staticmethod
    def increment_citation_counter():
        """为当前线程的计数器加一"""
        if not hasattr(Utils._local, 'citation_counter'):
            Utils._local.citation_counter = 1
        Utils._local.citation_counter += 1

    @staticmethod
    def safe_filter_grok_tags(text, citations=None):
        if not text or not isinstance(text, str):
            return text

        # 移除工具卡片
        text = re.sub(r'\s*<xai:tool_usage_card>.*?</xai:tool_usage_card>\s*', '', text, flags=re.DOTALL)

        if citations:
            # 2. 定义一个内嵌函数来处理替换，它会使用上面线程安全的计数器方法
            def replace_render_tag(match):
                card_id = match.group(1)
                if card_id in citations:
                    url = citations[card_id]
                    # 从线程局部存储中获取当前计数
                    counter = Utils.get_citation_counter()
                    replacement = f" [信源 {counter}]({url})"
                    # 增加当前线程的计数
                    Utils.increment_citation_counter()
                    return replacement
                else:
                    return " [信源信息缺失]"
            
            text = re.sub(r'<grok:render.*?card_id="([^"]+)".*?>.*?</grok:render>', replace_render_tag, text, flags=re.DOTALL)
        else:
            # 如果没有提供信源字典，就按老方法直接移除标签
            text = re.sub(r'<grok:render.*?>.*?</grok:render>', ' ', text, flags=re.DOTALL)

        return text

    @staticmethod
    def organize_search_results(search_results):
        if not search_results or 'results' not in search_results:
            return ''

        results = search_results['results']
        formatted_results = []

        for index, result in enumerate(results):
            title = result.get('title', '未知标题')
            url = result.get('url', '#')
            preview = result.get('preview', '无预览内容')

            formatted_result = f"\r\n<details><summary>资料[{index}]: {title}</summary>\r\n{preview}\r\n\n[{title}]({url})\r\n</details>\n"
            formatted_results.append(formatted_result)

        return '\n\n'.join(formatted_results)
        
    @staticmethod
    def create_auth_headers(model, is_return=False):
        return token_manager.get_next_token_for_model(model, is_return)

    @staticmethod
    def get_proxy_options():
        proxy = CONFIG["API"]["PROXY"]
        proxy_options = {}

        if proxy:
            logger.info(f"使用代理: {proxy}", "Server")
            
            if proxy.startswith("socks5://"):
                proxy_options["proxy"] = proxy
            
                if '@' in proxy:
                    auth_part = proxy.split('@')[0].split('://')[1]
                    if ':' in auth_part:
                        username, password = auth_part.split(':')
                        proxy_options["proxy_auth"] = (username, password)
            else:
                proxy_options["proxies"] = {"https": proxy, "http": proxy}     
        return proxy_options

class GrokApiClient:
    def __init__(self, model_id):
        if model_id not in CONFIG["MODELS"]:
            raise ValueError(f"不支持的模型: {model_id}")
        self.model_id = CONFIG["MODELS"][model_id]

    def process_message_content(self, content):
        if isinstance(content, str):
            return content
        return None

    def get_image_type(self, base64_string):
        mime_type = 'image/jpeg'
        if 'data:image' in base64_string:
            import re
            matches = re.search(r'data:([a-zA-Z0-9]+\/[a-zA-Z0-9-.+]+);base64,', base64_string)
            if matches:
                mime_type = matches.group(1)

        extension = mime_type.split('/')[1]
        file_name = f"image.{extension}"

        return {
            "mimeType": mime_type,
            "fileName": file_name
        }
        
    def upload_base64_file(self, message, model):
        try:
            message_base64 = base64.b64encode(message.encode('utf-8')).decode('utf-8')
            upload_data = {
                "fileName": "message.txt",
                "fileMimeType": "text/plain",
                "content": message_base64
            }

            logger.info("发送文字文件请求", "Server")
            cookie = f"{Utils.create_auth_headers(model, True)};{CONFIG['SERVER']['CF_CLEARANCE']}"
            proxy_options = Utils.get_proxy_options()

            def make_upload_request(**request_kwargs):
                return curl_requests.post(
                    "https://grok.com/rest/app-chat/upload-file",
                    json=upload_data,
                    impersonate="chrome133a",
                    **request_kwargs
                )

            response = smart_grok_request_with_fallback(
                make_upload_request,
                headers={
                    **get_default_headers(),
                    "Cookie": cookie
                },
                **proxy_options
            )

            if response.status_code != 200:
                logger.error(f"上传文件失败,状态码:{response.status_code}", "Server")
                raise Exception(f"上传文件失败,状态码:{response.status_code}")

            result = response.json()
            logger.info(f"上传文件成功: {result}", "Server")
            return result.get("fileMetadataId", "")

        except Exception as error:
            logger.error(str(error), "Server")
            raise Exception(f"上传文件失败,状态码:{response.status_code}")

    def upload_base64_image(self, base64_data, url, model):
        try:
            if 'data:image' in base64_data:
                image_buffer = base64_data.split(',')[1]
            else:
                image_buffer = base64_data

            image_info = self.get_image_type(base64_data)
            mime_type = image_info["mimeType"]
            file_name = image_info["fileName"]

            upload_data = {
                "fileName": file_name,
                "fileMimeType": mime_type,
                "content": image_buffer
            }

            logger.info("发送图片文件请求", "Server")

            proxy_options = Utils.get_proxy_options()
            cookie = f"{Utils.create_auth_headers(model, True)};{CONFIG['SERVER']['CF_CLEARANCE']}"

            def make_image_upload_request(**request_kwargs):
                return curl_requests.post(
                    url,
                    json=upload_data,
                    impersonate="chrome133a",
                    **request_kwargs
                )

            response = smart_grok_request_with_fallback(
                make_image_upload_request,
                headers={
                    **get_default_headers(),
                    "Cookie": cookie
                },
                **proxy_options
            )

            if response.status_code != 200:
                logger.error(f"上传图片失败,状态码:{response.status_code}, 响应: {response.text}", "Server")
                return ''

            result = response.json()
            logger.info(f"上传图片成功: {result}", "Server")
            return result.get("fileMetadataId", "")

        except Exception as error:
            logger.error(f"上传图片时发生异常: {str(error)}", "Server")
            return ''

    def prepare_chat_request(self, request):
        if ((request["model"] == 'grok-4-imageGen' or request["model"] == 'grok-3-imageGen') and
            not CONFIG["API"]["PICGO_KEY"] and not CONFIG["API"]["TUMY_KEY"] and
            request.get("stream", False)):
            raise ValueError("该模型流式输出需要配置PICGO或者TUMY图床密钥!")

        todo_messages = request["messages"]
        if request["model"] in ['grok-4-imageGen', 'grok-3-imageGen', 'grok-3-deepsearch']:
            last_message = todo_messages[-1]
            if last_message["role"] != 'user':
                raise ValueError('此模型最后一条消息必须是用户消息!')
            todo_messages = [last_message]
        file_attachments = []
        messages = ''
        last_role = None
        last_content = ''
        message_length = 0
        convert_to_file = False
        last_message_content = ''
        search = request["model"] in ['grok-4-search', 'grok-3-search']
        deepsearchPreset = ''
        if request["model"] == 'grok-3-deepsearch':
            deepsearchPreset = 'default'
        elif request["model"] == 'grok-3-deepersearch':
            deepsearchPreset = 'deeper'

        def remove_think_tags(text):
            import re
            text = re.sub(r'<think>[\s\S]*?<\/think>', '', text).strip()
            text = re.sub(r'!\[image\]\(data:.*?base64,.*?\)', '[图片]', text)
            return text

        def process_content(content):
            if isinstance(content, list):
                text_content = ''
                for item in content:
                    if item["type"] == 'image_url':
                        text_content += ("[图片]" if not text_content else '\n[图片]')
                    elif item["type"] == 'text':
                        text_content += (remove_think_tags(item["text"]) if not text_content else '\n' + remove_think_tags(item["text"]))
                return text_content
            elif isinstance(content, dict) and content is not None:
                if content["type"] == 'image_url':
                    return "[图片]"
                elif content["type"] == 'text':
                    return remove_think_tags(content["text"])
            return remove_think_tags(self.process_message_content(content))
            
        for current in todo_messages:
            role = 'assistant' if current["role"] == 'assistant' else 'user'
            is_last_message = current == todo_messages[-1]

            if is_last_message and "content" in current:
                if isinstance(current["content"], list):
                    for item in current["content"]:
                        if item["type"] == 'image_url':
                            processed_image = self.upload_base64_image(
                                item["image_url"]["url"],
                                f"{CONFIG['API']['BASE_URL']}/rest/app-chat/upload-file",
                                request["model"]
                            )
                            if processed_image:
                                file_attachments.append(processed_image)
                elif isinstance(current["content"], dict) and current["content"].get("type") == 'image_url':
                    processed_image = self.upload_base64_image(
                        current["content"]["image_url"]["url"],
                        f"{CONFIG['API']['BASE_URL']}/rest/app-chat/upload-file",
                        request["model"]
                    )
                    if processed_image:
                        file_attachments.append(processed_image)

            text_content = process_content(current.get("content", ""))
            if is_last_message and convert_to_file:
                last_message_content = f"{role.upper()}: {text_content or '[图片]'}\n"
                continue
            if text_content or (is_last_message and file_attachments):
                if role == last_role and text_content:
                    last_content += '\n' + text_content
                    messages = messages[:messages.rindex(f"{role.upper()}: ")] + f"{role.upper()}: {last_content}\n"
                else:
                    messages += f"{role.upper()}: {text_content or '[图片]'}\n"
                    last_content = text_content
                    last_role = role
            message_length += len(messages)
            if message_length >= 40000:
                convert_to_file = True
               
        if convert_to_file:
            file_id = self.upload_base64_file(messages, request["model"])
            if file_id:
                file_attachments.insert(0, file_id)
            messages = last_message_content.strip()
        if messages.strip() == '':
            if convert_to_file:
                messages = '基于txt文件内容进行回复：'
            else:
                raise ValueError('消息内容为空!')

        req_model = request.get("model")
        is_fast = req_model in ("grok-4-fast", "grok-3-fast")
        
        payload = {
            "temporary": CONFIG["API"].get("IS_TEMP_CONVERSATION", False),
            "modelName": self.model_id,
            "message": messages.strip(),
            "fileAttachments": file_attachments[:4],
            "imageAttachments": [],
            "disableSearch": False,
            "enableImageGeneration": True,
            "returnImageBytes": False,
            "returnRawGrokInXaiRequest": False,
            "enableImageStreaming": False,
            "imageGenerationCount": 1,
            "forceConcise": False,
            "toolOverrides": {
                "imageGen": request["model"] in ['grok-4-imageGen', 'grok-3-imageGen'],
                "webSearch": search,
                "xSearch": search,
                "xMediaSearch": search,
                "trendsSearch": search,
                "xPostAnalyze": search
            },
            "enableSideBySide": True,
            "sendFinalMetadata": True,
            "customPersonality": "",
            "deepsearchPreset": deepsearchPreset,
            "isReasoning": request["model"] == 'grok-3-reasoning',
            "disableTextFollowUps": True
        }
        
        # 仅在 -fast 变体时附带 fast/low 提示
        if is_fast:
            payload["mode"] = "fast"        # 抓包里看到的顶层模式
            payload["effort"] = "low"       # 抓包里 effort=low
            payload["requestMetadata"] = {  # 响应里是这个驼峰键；请求侧也用它
                "model": self.model_id,     # 映射后：grok-4 或 grok-3
                "mode": "MODEL_MODE_FAST",
                "effort": "LOW"
            }
        
        return payload
class MessageProcessor:
    @staticmethod
    def create_chat_response(message, model, is_stream=False):
        base_response = {
            "id": f"chatcmpl-{uuid.uuid4()}",
            "created": int(time.time()),
            "model": model
        }

        if is_stream:
            return {
                **base_response,
                "object": "chat.completion.chunk",
                "choices": [{
                    "index": 0,
                    "delta": {
                        "content": message
                    }
                }]
            }

        return {
            **base_response,
            "object": "chat.completion",
            "choices": [{
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": message
                },
                "finish_reason": "stop"
            }],
            "usage": None
        }

def process_model_response(response, model):
    result = {"token": None, "type": None} 
    AGENT_MODELS = ['grok-4-heavy', 'grok-4', 'grok-3-deepersearch', 'grok-3-deepsearch', 'grok-4-mini-thinking-tahoe']

    if response.get("cachedImageGenerationResponse"):
        return result 

    message_tag = response.get("messageTag")
    token = response.get("token")
    
    if message_tag == 'heartbeat':
        result["type"] = 'heartbeat'
        return result

    if model not in AGENT_MODELS and response.get("modelResponse"):
        return result

    if response.get("modelResponse") and isinstance(response["modelResponse"], dict):
        final_message = response["modelResponse"].get("message")
        if final_message:
            result["token"] = final_message
            result["type"] = 'content'
        return result

    is_thinking_content = False
    if model in AGENT_MODELS:
        THINKING_TAGS = {'header', 'summary', 'raw_function_result', 'citedWebSearchResults', 'tool_usage_card'}
        if message_tag in THINKING_TAGS or response.get("isThinking") or response.get("messageStepId"):
            is_thinking_content = True
    
    if is_thinking_content:
        if not CONFIG["SHOW_THINKING"]:
            return result
        else:
            content_to_send = token
            if response.get('webSearchResults') and CONFIG["ISSHOW_SEARCH_RESULTS"]:
                content_to_send = Utils.organize_search_results(response['webSearchResults'])
            
            if content_to_send:
                result["token"] = content_to_send
                result["type"] = 'thinking'
            return result
    
    if token:
        result["token"] = token
        result["type"] = 'content'
        return result

    return result
def handle_image_response(image_url):
    max_retries = 2
    retry_count = 0
    image_base64_response = None

    while retry_count < max_retries:
        try:
            proxy_options = Utils.get_proxy_options()

            # 使用智能重试机制发起图片下载请求
            def make_image_download_request(**request_kwargs):
                return curl_requests.get(
                    f"https://assets.grok.com/{image_url}",
                    impersonate="chrome133a",
                    **request_kwargs
                )

            image_base64_response = smart_grok_request_with_fallback(
                make_image_download_request,
                headers={
                    **get_default_headers(),
                    "Cookie": CONFIG["SERVER"]['COOKIE']
                },
                **proxy_options
            )

            if image_base64_response.status_code == 200:
                break

            retry_count += 1
            if retry_count == max_retries:
                raise Exception(f"上游服务请求失败! status: {image_base64_response.status_code}")

            time.sleep(CONFIG["API"]["RETRY_TIME"] / 1000 * retry_count)

        except Exception as error:
            logger.error(str(error), "Server")
            retry_count += 1
            if retry_count == max_retries:
                raise

            time.sleep(CONFIG["API"]["RETRY_TIME"] / 1000 * retry_count)

    image_buffer = image_base64_response.content

    if not CONFIG["API"]["PICGO_KEY"] and not CONFIG["API"]["TUMY_KEY"]:
        base64_image = base64.b64encode(image_buffer).decode('utf-8')
        image_content_type = image_base64_response.headers.get('content-type', 'image/jpeg')
        return f"![image](data:{image_content_type};base64,{base64_image})"

    logger.info("开始上传图床", "Server")

    if CONFIG["API"]["PICGO_KEY"]:
        files = {'source': ('image.jpg', image_buffer, 'image/jpeg')}
        headers = {
            "X-API-Key": CONFIG["API"]["PICGO_KEY"]
        }

        response_url = requests.post(
            "https://www.picgo.net/api/1/upload",
            files=files,
            headers=headers
        )

        if response_url.status_code != 200:
            return "生图失败，请查看PICGO图床密钥是否设置正确"
        else:
            logger.info("生图成功", "Server")
            result = response_url.json()
            return f"![image]({result['image']['url']})"


    elif CONFIG["API"]["TUMY_KEY"]:
        files = {'file': ('image.jpg', image_buffer, 'image/jpeg')}
        headers = {
            "Accept": "application/json",
            'Authorization': f"Bearer {CONFIG['API']['TUMY_KEY']}"
        }

        response_url = requests.post(
            "https://tu.my/api/v1/upload",
            files=files,
            headers=headers
        )

        if response_url.status_code != 200:
            return "生图失败，请查看TUMY图床密钥是否设置正确"
        else:
            try:
                result = response_url.json()
                logger.info("生图成功", "Server")
                return f"![image]({result['data']['links']['url']})"
            except Exception as error:
                logger.error(str(error), "Server")
                return "生图失败，请查看TUMY图床密钥是否设置正确"
                
def handle_non_stream_response(response, model):
    logger.info("开始处理非流式响应", "Server")
    stream = response.iter_lines()
    full_response = ""
    final_agent_response = None
    image_url_found = None
    citations = {}

    AGENT_MODELS = ['grok-4-heavy', 'grok-4', 'grok-3-deepersearch', 'grok-3-deepsearch', 'grok-4-mini-thinking-tahoe']

    for chunk in stream:
        if not chunk: continue
        try:
            line_json = json.loads(chunk.decode("utf-8").strip())
            if line_json.get("error"): continue

            response_data = line_json.get("result", {}).get("response")
            if not response_data: continue

            if "cardAttachment" in response_data and response_data["cardAttachment"].get("jsonData"):
                try:
                    card_data = json.loads(response_data["cardAttachment"]["jsonData"])
                    if card_data.get("id") and card_data.get("url"):
                        citations[card_data["id"]] = card_data["url"]
                except json.JSONDecodeError: pass

            if "cachedImageGenerationResponse" in response_data:
                image_url_found = response_data["cachedImageGenerationResponse"].get("imageUrl")

            if model in AGENT_MODELS:
                if response_data.get("modelResponse") and isinstance(response_data["modelResponse"], dict):
                    final_agent_response = response_data["modelResponse"].get("message", "")
            else:
                is_process_info = (
                    response_data.get("isThinking") or 
                    response_data.get("messageStepId") or
                    response_data.get("modelResponse") or
                    response_data.get("messageTag") not in [None, "final"]
                )
                token = response_data.get("token")
                if token is not None and not is_process_info:
                    full_response += token
        
        except Exception as e:
            logger.error(f"处理非流式响应行时出错: {str(e)}", "Server")
            continue

    if image_url_found:
        return handle_image_response(image_url_found)
    
    if model in AGENT_MODELS and final_agent_response is not None:
        return Utils.safe_filter_grok_tags(final_agent_response, citations)
    
    return Utils.safe_filter_grok_tags(full_response, citations)
def handle_stream_response(response, model):
    
    Utils.reset_citation_counter()
    initial_payload = {
        "id": f"chatcmpl-{uuid.uuid4()}",
        "object": "chat.completion.chunk",
        "created": int(time.time()),
        "model": model,
        "choices": [{"index": 0, "delta": {"role": "assistant", "content": ""}, "finish_reason": None}]
    }
    yield f"data: {json.dumps(initial_payload)}\n\n".encode('utf-8')

    citations = {}
    AGENT_MODELS = ['grok-4-heavy', 'grok-4', 'grok-3-deepersearch', 'grok-3-deepsearch', 'grok-4-mini-thinking-tahoe']

    if model in AGENT_MODELS:
        def generate_agent():
            logger.info(f"使用 Agent 模型专用逻辑处理: {model}", "Server")
            stream = response.iter_lines()
            is_in_think_block = False
            emitted_content_from_tokens = False

            for chunk in stream:
                if not chunk: continue
                try:
                    line_json = json.loads(chunk.decode("utf-8").strip())
                    if line_json.get("error"): continue
                    response_data = line_json.get("result", {}).get("response")
                    if not response_data: continue
                    if "cardAttachment" in response_data and response_data["cardAttachment"].get("jsonData"):
                        try:
                            card_data = json.loads(response_data["cardAttachment"]["jsonData"])
                            if card_data.get("id") and card_data.get("url"):
                                citations[card_data["id"]] = card_data["url"]
                        except json.JSONDecodeError: pass

                    # 忽略 streaming 末尾重复的整体 modelResponse，除非前面没收到任何 token
                    if isinstance(response_data.get("modelResponse"), dict):
                        if emitted_content_from_tokens:
                            continue
                        clean_message = Utils.safe_filter_grok_tags(response_data["modelResponse"].get("message", ""), citations)
                        if clean_message:
                            if is_in_think_block:
                                is_in_think_block = False
                                payload = MessageProcessor.create_chat_response('</think>\n\n', model, True)
                                yield f"data: {json.dumps(payload)}\n\n".encode('utf-8')
                            payload = MessageProcessor.create_chat_response(clean_message, model, True)
                            yield f"data: {json.dumps(payload)}\n\n".encode('utf-8')
                        continue

                    result = process_model_response(response_data, model)
                    if result.get("type") == 'heartbeat':
                        yield b": ping\n\n"
                        continue
                    if result.get("token"):
                        if result.get("type") == 'thinking':
                            if not is_in_think_block:
                                is_in_think_block = True
                                payload = MessageProcessor.create_chat_response('<think>\n', model, True)
                                yield f"data: {json.dumps(payload)}\n\n".encode('utf-8')
                            clean_token = Utils.safe_filter_grok_tags(result["token"], citations)
                            if clean_token:
                                payload = MessageProcessor.create_chat_response(clean_token, model, True)
                                yield f"data: {json.dumps(payload)}\n\n".encode('utf-8')
                        elif result.get("type") == 'content':
                            if is_in_think_block:
                                is_in_think_block = False
                                payload = MessageProcessor.create_chat_response('</think>\n\n', model, True)
                                yield f"data: {json.dumps(payload)}\n\n".encode('utf-8')
                            clean_token = Utils.safe_filter_grok_tags(result["token"], citations)
                            if clean_token:
                                emitted_content_from_tokens = True
                                payload = MessageProcessor.create_chat_response(clean_token, model, True)
                                yield f"data: {json.dumps(payload)}\n\n".encode('utf-8')
                except Exception as e:
                    logger.error(f"处理 Agent 流时出错: {str(e)}", "Server")
                    continue
            if is_in_think_block:
                payload = MessageProcessor.create_chat_response('</think>\n\n', model, True)
                yield f"data: {json.dumps(payload)}\n\n".encode('utf-8')
            yield b"data: [DONE]\n\n"
        for chunk in generate_agent():
            yield chunk
    else:
        def generate_standard_fixed():
            logger.info(f"使用标准模型逻辑处理 (严格过滤模式): {model}", "Server")
            stream = response.iter_lines()
            is_img_gen = False
            is_img_gen2 = False
            for chunk in stream:
                if not chunk: continue
                try:
                    line_json = json.loads(chunk.decode("utf-8").strip())
                    if line_json.get("error"): continue
                    response_data = line_json.get("result", {}).get("response")
                    if not response_data: continue
                    if "cardAttachment" in response_data and response_data["cardAttachment"].get("jsonData"):
                        try:
                            card_data = json.loads(response_data["cardAttachment"]["jsonData"])
                            if card_data.get("id") and card_data.get("url"):
                                citations[card_data["id"]] = card_data["url"]
                        except json.JSONDecodeError: pass
                    if response_data.get("doImgGen") or response_data.get("imageAttachmentInfo"):
                        is_img_gen = True
                    if "cachedImageGenerationResponse" in response_data and not is_img_gen2:
                        image_url = response_data["cachedImageGenerationResponse"].get("imageUrl")
                        if image_url:
                            is_img_gen2 = True
                            image_data = handle_image_response(image_url)
                            payload = MessageProcessor.create_chat_response(image_data, model, True)
                            yield f"data: {json.dumps(payload)}\n\n".encode('utf-8')
                            break 
                    if is_img_gen and not is_img_gen2:
                        continue
                    is_process_info = (
                        response_data.get("isThinking") or 
                        response_data.get("messageStepId") or
                        response_data.get("modelResponse") or
                        response_data.get("messageTag") not in [None, "final"]
                    )
                    token = response_data.get("token")
                    if token and not is_process_info:
                        clean_token = Utils.safe_filter_grok_tags(token, citations)
                        payload = MessageProcessor.create_chat_response(clean_token, model, True)
                        yield f"data: {json.dumps(payload)}\n\n".encode('utf-8')
                except Exception as e:
                    logger.error(f"处理标准流时出错: {str(e)}", "Server")
                    continue
            yield b"data: [DONE]\n\n"
        for chunk in generate_standard_fixed():
            yield chunk
def initialization():
    sso_array = os.environ.get("SSO", "").split(',')
    sso_heavy_array = os.environ.get("SSO_HEAVY", "").split(',') # 新增 heavy sso 环境变量

    logger.info("开始加载令牌", "Server")
    token_manager.load_token_status()
    
    for sso in sso_array:
        if sso:
            token_manager.add_token(f"sso-rw={sso};sso={sso}", token_type="normal", isinitialization=True)
            
    for sso in sso_heavy_array:
        if sso:
            token_manager.add_token(f"sso-rw={sso};sso={sso}", token_type="heavy", isinitialization=True)

    token_manager.save_token_status()

    all_tokens = token_manager.get_all_tokens() # 假设你有一个 get_all_tokens 方法
    logger.info(f"成功加载令牌: {json.dumps(all_tokens, indent=2)}", "Server")
    logger.info(f"令牌加载完成，共加载: {len(all_tokens)}个令牌", "Server")

    if CONFIG["API"]["PROXY"]:
        logger.info(f"代理已设置: {CONFIG['API']['PROXY']}", "Server")


token_manager = AuthTokenManager()
initialization()

app = Flask(__name__)
app.wsgi_app = ProxyFix(app.wsgi_app)
app.secret_key = os.environ.get('FLASK_SECRET_KEY') or secrets.token_hex(16)
app.json.sort_keys = False


@app.route('/manager/login', methods=['GET', 'POST'])
def manager_login():
    if CONFIG["ADMIN"]["MANAGER_SWITCH"]:
        if request.method == 'POST':
            password = request.form.get('password')
            if password == CONFIG["ADMIN"]["PASSWORD"]:
                session['is_logged_in'] = True
                return redirect('/manager')
            return render_template('login.html', error=True)
        return render_template('login.html', error=False)
    else:
        return redirect('/')

def check_auth():
    return session.get('is_logged_in', False)

@app.route('/manager')
def manager():
    if not check_auth():
        return redirect('/manager/login')
    return render_template('manager.html')

@app.route('/manager/api/get')
def get_manager_tokens():
    if not check_auth():
        return jsonify({"error": "Unauthorized"}), 401
    return jsonify(token_manager.get_token_status_map())

@app.route('/manager/api/add', methods=['POST'])
def add_manager_token():
    if not check_auth():
        return jsonify({"error": "Unauthorized"}), 401
    try:
        sso = request.json.get('sso')
        if not sso:
            return jsonify({"error": "SSO token is required"}), 400
        token_manager.add_token(f"sso-rw={sso};sso={sso}")
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/manager/api/delete', methods=['POST'])
def delete_manager_token():
    if not check_auth():
        return jsonify({"error": "Unauthorized"}), 401
    try:
        sso = request.json.get('sso')
        if not sso:
            return jsonify({"error": "SSO token is required"}), 400
        token_manager.delete_token(f"sso-rw={sso};sso={sso}")
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    
@app.route('/manager/api/cf_clearance', methods=['POST'])   
def setCf_Manager_clearance():
    if not check_auth():
        return jsonify({"error": "Unauthorized"}), 401
    try:
        cf_clearance = request.json.get('cf_clearance')
        if not cf_clearance:
            return jsonify({"error": "cf_clearance is required"}), 400
        CONFIG["SERVER"]['CF_CLEARANCE'] = cf_clearance
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/get/tokens', methods=['GET'])
def get_tokens():
    auth_token = request.headers.get('Authorization', '').replace('Bearer ', '')
    if CONFIG["API"]["IS_CUSTOM_SSO"]:
        return jsonify({"error": '自定义的SSO令牌模式无法获取轮询sso令牌状态'}), 403
    elif auth_token != CONFIG["API"]["API_KEY"]:
        return jsonify({"error": 'Unauthorized'}), 401
    return jsonify(token_manager.get_token_status_map())

@app.route('/add/token', methods=['POST'])
def add_token():
    auth_token = request.headers.get('Authorization', '').replace('Bearer ', '')
    if CONFIG["API"]["IS_CUSTOM_SSO"]:
        return jsonify({"error": '自定义的SSO令牌模式无法添加sso令牌'}), 403
    elif auth_token != CONFIG["API"]["API_KEY"]:
        return jsonify({"error": 'Unauthorized'}), 401

    try:
        sso = request.json.get('sso')
        token_manager.add_token(f"sso-rw={sso};sso={sso}")
        return jsonify(token_manager.get_token_status_map().get(sso, {})), 200
    except Exception as error:
        logger.error(str(error), "Server")
        return jsonify({"error": '添加sso令牌失败'}), 500
    
@app.route('/set/cf_clearance', methods=['POST'])
def setCf_clearance():
    auth_token = request.headers.get('Authorization', '').replace('Bearer ', '')
    if auth_token != CONFIG["API"]["API_KEY"]:
        return jsonify({"error": 'Unauthorized'}), 401
    try:
        cf_clearance = request.json.get('cf_clearance')
        CONFIG["SERVER"]['CF_CLEARANCE'] = cf_clearance
        return jsonify({"message": '设置cf_clearance成功'}), 200
    except Exception as error:
        logger.error(str(error), "Server")
        return jsonify({"error": '设置cf_clearance失败'}), 500
    
@app.route('/delete/token', methods=['POST'])
def delete_token():
    auth_token = request.headers.get('Authorization', '').replace('Bearer ', '')
    if CONFIG["API"]["IS_CUSTOM_SSO"]:
        return jsonify({"error": '自定义的SSO令牌模式无法删除sso令牌'}), 403
    elif auth_token != CONFIG["API"]["API_KEY"]:
        return jsonify({"error": 'Unauthorized'}), 401

    try:
        sso = request.json.get('sso')
        token_manager.delete_token(f"sso-rw={sso};sso={sso}")
        return jsonify({"message": '删除sso令牌成功'}), 200
    except Exception as error:
        logger.error(str(error), "Server")
        return jsonify({"error": '删除sso令牌失败'}), 500

@app.route('/v1/models', methods=['GET'])
def get_models():
    return jsonify({
        "object": "list",
        "data": [
            {
                "id": model,
                "object": "model",
                "created": int(time.time()),
                "owned_by": "grok"
            }
            for model in CONFIG["MODELS"].keys()
        ]
    })
    
    
def stream_with_active_heartbeat(source_stream, interval=30):
    q = queue.Queue()

    def reader_thread():
        try:
            for chunk in source_stream:
                q.put(chunk)
        except Exception as e:
            logger.error(f"源数据流发生错误: {e}", "HeartbeatWrapper")
            q.put(e)
        finally:
            q.put(None)

    thread = threading.Thread(target=reader_thread)
    thread.daemon = True
    thread.start()

    # 立刻写首字节 + 2KB 填充（SSE 注释，客户端不会解析为 JSON）
    yield (":" + (" " * 2048) + "\n").encode('utf-8')

    last_sent = time.monotonic()

    while True:
        try:
            timeout = max(0, interval - (time.monotonic() - last_sent))
            chunk = q.get(timeout=timeout) if timeout > 0 else q.get_nowait()

            if chunk is None:
                break
            if isinstance(chunk, Exception):
                raise chunk

            last_sent = time.monotonic()
            yield chunk

        except queue.Empty:
            # 主动心跳用 SSE 注释，避免客户端按 OpenAI chunk 解析
            logger.info("30秒无响应，发送主动心跳", "HeartbeatWrapper")
            last_sent = time.monotonic()
            yield b": keep-alive\n\n"

@app.route('/v1/chat/completions', methods=['POST'])
def chat_completions():
    response_status_code = 500
    try:
        # --- 认证逻辑 (与你的版本完全不变) ---
        auth_token = request.headers.get('Authorization', '').replace('Bearer ', '')
        if auth_token:
            if CONFIG["API"]["IS_CUSTOM_SSO"]:
                result = f"sso={auth_token};sso-rw={auth_token}"
                token_manager.set_token(result) # 注意：自定义SSO模式会覆盖分组逻辑
            elif auth_token != CONFIG["API"]["API_KEY"]:
                return jsonify({"error": 'Unauthorized'}), 401
        else:
            return jsonify({"error": 'API_KEY缺失'}), 401

        # --- 数据准备 (与你的版本完全不变) ---
        data = request.json
        model = data.get("model")
        stream = data.get("stream", False)

        grok_client = GrokApiClient(model)
        request_payload = grok_client.prepare_chat_request(data)
        logger.info(f"为模型 {model} 准备的请求体: {json.dumps(request_payload, indent=2)}", "ChatAPI")
        
        # --- 核心修改：引入带上限的试错循环 ---
        MAX_SWITCH_ATTEMPTS = 5 

        for attempt in range(MAX_SWITCH_ATTEMPTS):
            # 1. "偷看"一下当前将要使用的SSO，方便日志记录和出错时移除
            current_sso_cookie = token_manager.get_next_token_for_model(model, is_return=True)
            
            if not current_sso_cookie:
                raise ValueError(f'模型 {model} 已无可用令牌可供尝试。')

            logger.info(f"第 {attempt + 1}/{MAX_SWITCH_ATTEMPTS} 次尝试，准备使用 SSO: {current_sso_cookie.split(';')[1]}", "ChatAPI")

            # 2. 正式获取SSO并消耗一次计数
            CONFIG["API"]["SIGNATURE_COOKIE"] = token_manager.get_next_token_for_model(model)

            # --- 准备请求 (这部分是从你的版本里移到循环内部的) ---
            logger.info(f"当前令牌: {json.dumps(CONFIG['API']['SIGNATURE_COOKIE'], indent=2)}", "Server")
            logger.info(f"当前可用模型的全部可用数量: {json.dumps(token_manager.get_remaining_token_request_capacity(), indent=2)}", "Server")
            
            if CONFIG['SERVER']['CF_CLEARANCE']:
                CONFIG["SERVER"]['COOKIE'] = f"{CONFIG['API']['SIGNATURE_COOKIE']};{CONFIG['SERVER']['CF_CLEARANCE']}" 
            else:
                CONFIG["SERVER"]['COOKIE'] = CONFIG['API']['SIGNATURE_COOKIE']

            try:
                proxy_options = Utils.get_proxy_options()

                # --- 发起请求 (与你的版本完全不变) ---
                def make_grok_request(**request_kwargs):
                    return curl_requests.post(
                        f"{CONFIG['API']['BASE_URL']}/rest/app-chat/conversations/new",
                        data=json.dumps(request_payload),
                        impersonate="chrome133a",
                        stream=True,
                        timeout=(10, 1800), # 加上我们之前讨论的防超时设置
                        **request_kwargs
                    )

                response = smart_grok_request_with_fallback(
                    make_grok_request,
                    headers={
                        **get_default_headers(),
                        "Cookie": CONFIG["SERVER"]['COOKIE']
                    },
                    **proxy_options
                )
                
                logger.info(f"使用 Cookie: {CONFIG['SERVER']['COOKIE']} 发起请求", "Server")

                # 3. --- 结果判断与处理 ---
                if response.status_code == 200:
                    response_status_code = 200
                    logger.info(f"SSO {current_sso_cookie.split(';')[1]} 请求成功。当前模型剩余可用令牌数: {token_manager.get_token_count_for_model(model)}", "Server")
                    
                    # 请求成功，处理响应并立即返回，结束整个函数
                    if stream:
                        # (这里的代码是我们之前修复好的，带主动心跳和反缓冲头的版本)
                        sse_gen = stream_with_active_heartbeat(handle_stream_response(response, model), interval=10)
                        resp = Response(stream_with_context(sse_gen), content_type='text/event-stream; charset=utf-8', direct_passthrough=True)
                        resp.headers['Cache-Control'] = 'no-cache, no-transform'
                        resp.headers['Connection'] = 'keep-alive'
                        resp.headers['X-Accel-Buffering'] = 'no'
                        return resp
                    else:
                        content = handle_non_stream_response(response, model)
                        return jsonify(MessageProcessor.create_chat_response(content, model))

                # 如果请求失败，则记录日志，将当前SSO移入冷却池，然后进入下一次循环
                logger.warning(
                    f"SSO {current_sso_cookie.split(';')[1]} 请求失败 (状态码: {response.status_code})，将移入冷却池并尝试下一个。",
                    "ChatAPI"
                )
                token_manager.remove_token_from_model(model, current_sso_cookie)
                # continue 会自动进入 for 循环的下一次迭代
            
            except Exception as e:
                logger.error(f"SSO {current_sso_cookie.split(';')[1]} 遭遇请求异常: {e}，将移入冷却池并尝试下一个。", "ChatAPI")
                token_manager.remove_token_from_model(model, current_sso_cookie)
                # continue 会自动进入 for 循环的下一次迭代
        
        # 如果 for 循环执行了 5 次都失败了，就会走到这里
        raise ValueError(f'已连续尝试 {MAX_SWITCH_ATTEMPTS} 个不同 SSO 均失败，请稍后重试或检查 SSO 池状态。')

    except Exception as error:
        logger.error(str(error), "ChatAPI")
        # 如果是认证错误或我们主动抛出的错误，可以用 400/500，否则用 500
        status_code_to_return = response_status_code if 'response_status_code' in locals() and response_status_code != 200 else 500
        return jsonify(
            {"error": {
                "message": str(error),
                "type": "server_error"
            }}), status_code_to_return
@app.route('/', defaults={'path': ''})
@app.route('/<path:path>')
def catch_all(path):
    return 'api运行正常', 200

if __name__ == '__main__':
    token_manager = AuthTokenManager()
    initialization()

    app.run(
        host='0.0.0.0',
        port=CONFIG["SERVER"]["PORT"],
        debug=False
    )
