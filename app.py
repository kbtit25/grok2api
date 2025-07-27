import os
import json
import uuid
import time
import base64
import sys
import inspect
import secrets
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
        'grok-4': 'grok-4',
        'grok-4-imageGen': 'grok-4',
        'grok-4-search': 'grok-4',
        "grok-3": "grok-3",
        "grok-3-search": "grok-3",
        "grok-3-imageGen": "grok-3",
        "grok-3-deepsearch": "grok-3",
        "grok-3-deepersearch": "grok-3",
        "grok-3-reasoning": "grok-3"
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

class AuthTokenManager:
    def __init__(self):
        self.token_model_map = {}
        self.expired_tokens = set()
        self.token_status_map = {}

        self.model_config = {
            "grok-4": {
                "RequestFrequency": 20,
                "ExpirationTime": 2 * 60 * 60 * 1000  # 1小时
            },
            "grok-3": {
                "RequestFrequency": 100,
                "ExpirationTime": 2 * 60 * 60 * 1000  # 2小时
            },
            "grok-3-deepsearch": {
                "RequestFrequency": 30,
                "ExpirationTime": 24 * 60 * 60 * 1000  # 24小时
            },
            "grok-3-deepersearch": {
                "RequestFrequency": 30,
                "ExpirationTime": 24 * 60 * 60 * 1000  # 24小时
            },
            "grok-3-reasoning": {
                "RequestFrequency": 30,
                "ExpirationTime": 24 * 60 * 60 * 1000  # 24小时
            }
        }
        self.token_reset_switch = False
        self.token_reset_timer = None
        self.load_token_status() # 加载令牌状态
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
    def add_token(self, token,isinitialization=False):
        sso = token.split("sso=")[1].split(";")[0]
        for model in self.model_config.keys():
            if model not in self.token_model_map:
                self.token_model_map[model] = []
            if sso not in self.token_status_map:
                self.token_status_map[sso] = {}

            existing_token_entry = next((entry for entry in self.token_model_map[model] if entry["token"] == token), None)

            if not existing_token_entry:
                self.token_model_map[model].append({
                    "token": token,
                    "RequestCount": 0,
                    "AddedTime": int(time.time() * 1000),
                    "StartCallTime": None
                })

                if model not in self.token_status_map[sso]:
                    self.token_status_map[sso][model] = {
                        "isValid": True,
                        "invalidatedTime": None,
                        "totalRequestCount": 0
                    }
        if not isinitialization:
            self.save_token_status()

    def set_token(self, token):
        models = list(self.model_config.keys())
        self.token_model_map = {model: [{
            "token": token,
            "RequestCount": 0,
            "AddedTime": int(time.time() * 1000),
            "StartCallTime": None
        }] for model in models}

        sso = token.split("sso=")[1].split(";")[0]
        self.token_status_map[sso] = {model: {
            "isValid": True,
            "invalidatedTime": None,
            "totalRequestCount": 0
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
            
            if normalized_model not in self.token_model_map:
                logger.error(f"模型 {normalized_model} 不存在", "TokenManager")
                return False
                
            if not self.token_model_map[normalized_model]:
                logger.error(f"模型 {normalized_model} 没有可用的token", "TokenManager")
                return False
                
            token_entry = self.token_model_map[normalized_model][0]
            
            # 确保RequestCount不会小于0
            new_count = max(0, token_entry["RequestCount"] - count)
            reduction = token_entry["RequestCount"] - new_count
            
            token_entry["RequestCount"] = new_count
            
            # 更新token状态
            if token_entry["token"]:
                sso = token_entry["token"].split("sso=")[1].split(";")[0]
                if sso in self.token_status_map and normalized_model in self.token_status_map[sso]:
                    self.token_status_map[sso][normalized_model]["totalRequestCount"] = max(
                        0, 
                        self.token_status_map[sso][normalized_model]["totalRequestCount"] - reduction
                    )
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

        if token_entry:
            if token_entry["StartCallTime"] is None:
                token_entry["StartCallTime"] = int(time.time() * 1000)

            if not self.token_reset_switch:
                self.start_token_reset_process()
                self.token_reset_switch = True

            token_entry["RequestCount"] += 1

            if token_entry["RequestCount"] > self.model_config[normalized_model]["RequestFrequency"]:
                self.remove_token_from_model(normalized_model, token_entry["token"])
                next_token_entry = self.token_model_map[normalized_model][0] if self.token_model_map[normalized_model] else None
                return next_token_entry["token"] if next_token_entry else None

            sso = token_entry["token"].split("sso=")[1].split(";")[0]
            if sso in self.token_status_map and normalized_model in self.token_status_map[sso]:
                if token_entry["RequestCount"] == self.model_config[normalized_model]["RequestFrequency"]:
                    self.token_status_map[sso][normalized_model]["isValid"] = False
                    self.token_status_map[sso][normalized_model]["invalidatedTime"] = int(time.time() * 1000)
                self.token_status_map[sso][normalized_model]["totalRequestCount"] += 1

                self.save_token_status()

            return token_entry["token"]

        return None

    def remove_token_from_model(self, model_id, token):
        normalized_model = self.normalize_model_name(model_id)

        if normalized_model not in self.token_model_map:
            logger.error(f"模型 {normalized_model} 不存在", "TokenManager")
            return False

        model_tokens = self.token_model_map[normalized_model]
        token_index = next((i for i, entry in enumerate(model_tokens) if entry["token"] == token), -1)

        if token_index != -1:
            removed_token_entry = model_tokens.pop(token_index)
            self.expired_tokens.add((
                removed_token_entry["token"],
                normalized_model,
                int(time.time() * 1000)
            ))

            if not self.token_reset_switch:
                self.start_token_reset_process()
                self.token_reset_switch = True

            logger.info(f"模型{model_id}的令牌已失效，已成功移除令牌: {token}", "TokenManager")
            return True

        logger.error(f"在模型 {normalized_model} 中未找到 token: {token}", "TokenManager")
        return False

    def get_expired_tokens(self):
        return list(self.expired_tokens)

    def normalize_model_name(self, model):
        if model.startswith('grok-') and 'deepsearch' not in model and 'reasoning' not in model:
            return '-'.join(model.split('-')[:2])
        return model

    def get_token_count_for_model(self, model_id):
        normalized_model = self.normalize_model_name(model_id)
        return len(self.token_model_map.get(normalized_model, []))

    def get_remaining_token_request_capacity(self):
        remaining_capacity_map = {}

        for model in self.model_config.keys():
            model_tokens = self.token_model_map.get(model, [])
            model_request_frequency = self.model_config[model]["RequestFrequency"]

            total_used_requests = sum(token_entry.get("RequestCount", 0) for token_entry in model_tokens)

            remaining_capacity = (len(model_tokens) * model_request_frequency) - total_used_requests
            remaining_capacity_map[model] = max(0, remaining_capacity)

        return remaining_capacity_map

    def get_token_array_for_model(self, model_id):
        normalized_model = self.normalize_model_name(model_id)
        return self.token_model_map.get(normalized_model, [])

    def start_token_reset_process(self):
        def reset_expired_tokens():
            now = int(time.time() * 1000)

            tokens_to_remove = set()
            for token_info in self.expired_tokens:
                token, model, expired_time = token_info
                expiration_time = self.model_config[model]["ExpirationTime"]

                if now - expired_time >= expiration_time:
                    if not any(entry["token"] == token for entry in self.token_model_map.get(model, [])):
                        if model not in self.token_model_map:
                            self.token_model_map[model] = []

                        self.token_model_map[model].append({
                            "token": token,
                            "RequestCount": 0,
                            "AddedTime": now,
                            "StartCallTime": None
                        })

                    sso = token.split("sso=")[1].split(";")[0]
                    if sso in self.token_status_map and model in self.token_status_map[sso]:
                        self.token_status_map[sso][model]["isValid"] = True
                        self.token_status_map[sso][model]["invalidatedTime"] = None
                        self.token_status_map[sso][model]["totalRequestCount"] = 0

                    tokens_to_remove.add(token_info)

            self.expired_tokens -= tokens_to_remove

            for model in self.model_config.keys():
                if model not in self.token_model_map:
                    continue

                for token_entry in self.token_model_map[model]:
                    if not token_entry.get("StartCallTime"):
                        continue

                    expiration_time = self.model_config[model]["ExpirationTime"]
                    if now - token_entry["StartCallTime"] >= expiration_time:
                        sso = token_entry["token"].split("sso=")[1].split(";")[0]
                        if sso in self.token_status_map and model in self.token_status_map[sso]:
                            self.token_status_map[sso][model]["isValid"] = True
                            self.token_status_map[sso][model]["invalidatedTime"] = None
                            self.token_status_map[sso][model]["totalRequestCount"] = 0

                        token_entry["RequestCount"] = 0
                        token_entry["StartCallTime"] = None

        import threading
        # 启动一个线程执行定时任务，每小时执行一次
        def run_timer():
            while True:
                reset_expired_tokens()
                time.sleep(3600)

        timer_thread = threading.Thread(target=run_timer)
        timer_thread.daemon = True
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

        token_entry = self.token_model_map[normalized_model][0]
        return token_entry["token"]

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
    def safe_filter_grok_tags(text):
        """
        只移除 <xai:tool_usage_card>，不再处理 <grok:render>。
        """
        if not text or not isinstance(text, str):
            return text
    
    # 我们只处理这一个标签
        start_tag, end_tag = ("<xai:tool_usage_card>", "</xai:tool_usage_card>")
    
        while True:
            end_index = text.rfind(end_tag)
            if end_index == -1:
                break
        
            start_index = text.rfind(start_tag, 0, end_index)
            if start_index == -1:
                break
        
            text = text[:start_index] + text[end_index + len(end_tag):]
            
    # 注意：我们依然保留 strip()，因为它对小总结是必要的。
    # 我们将在下游处理换行符的问题。
        return text.strip()
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

            # 使用智能重试机制发起文件上传请求
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
    def upload_base64_image(self, base64_data, url):
        try:
            if 'data:image' in base64_data:
                image_buffer = base64_data.split(',')[1]
            else:
                image_buffer = base64_data

            image_info = self.get_image_type(base64_data)
            mime_type = image_info["mimeType"]
            file_name = image_info["fileName"]

            upload_data = {
                "rpc": "uploadFile",
                "req": {
                    "fileName": file_name,
                    "fileMimeType": mime_type,
                    "content": image_buffer
                }
            }

            logger.info("发送图片请求", "Server")

            proxy_options = Utils.get_proxy_options()

            # 使用智能重试机制发起图片上传请求
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
                    "Cookie": CONFIG["SERVER"]['COOKIE']
                },
                **proxy_options
            )

            if response.status_code != 200:
                logger.error(f"上传图片失败,状态码:{response.status_code}", "Server")
                return ''

            result = response.json()
            logger.info(f"上传图片成功: {result}", "Server")
            return result.get("fileMetadataId", "")

        except Exception as error:
            logger.error(str(error), "Server")
            return ''
    # def convert_system_messages(self, messages):
    #     try:
    #         system_prompt = []
    #         i = 0
    #         while i < len(messages):
    #             if messages[i].get('role') != 'system':
    #                 break

    #             system_prompt.append(self.process_message_content(messages[i].get('content')))
    #             i += 1

    #         messages = messages[i:]
    #         system_prompt = '\n'.join(system_prompt)

    #         if not messages:
    #             raise ValueError("没有找到用户或者AI消息")
    #         return {"system_prompt":system_prompt,"messages":messages}
    #     except Exception as error:
    #         logger.error(str(error), "Server")
    #         raise ValueError(error)
    def prepare_chat_request(self, request):
        if ((request["model"] == 'grok-4-imageGen' or request["model"] == 'grok-3-imageGen') and
            not CONFIG["API"]["PICGO_KEY"] and not CONFIG["API"]["TUMY_KEY"] and
            request.get("stream", False)):
            raise ValueError("该模型流式输出需要配置PICGO或者TUMY图床密钥!")

        # system_message, todo_messages = self.convert_system_messages(request["messages"]).values()
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

        # 移除<think>标签及其内容和base64图片
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
                                f"{CONFIG['API']['BASE_URL']}/api/rpc"
                            )
                            if processed_image:
                                file_attachments.append(processed_image)
                elif isinstance(current["content"], dict) and current["content"].get("type") == 'image_url':
                    processed_image = self.upload_base64_image(
                        current["content"]["image_url"]["url"],
                        f"{CONFIG['API']['BASE_URL']}/api/rpc"
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
        return {
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

    # --- 图片逻辑 (保持不变) ---
    if CONFIG["IS_IMG_GEN"]:
        if response.get("cachedImageGenerationResponse") and not CONFIG["IS_IMG_GEN2"]:
            result["imageUrl"] = response["cachedImageGenerationResponse"]["imageUrl"]
            result["type"] = 'image_url'
        return result

    message_tag = response.get("messageTag")
    token = response.get("token")
    
    # 规则 1：心跳 (通用，最高优先级)
    if message_tag == 'heartbeat':
        result["type"] = 'heartbeat'
        return result

    # 规则 2：最终答案块 (所有模型的唯一、最终、可信来源)
    if response.get("modelResponse") and isinstance(response["modelResponse"], dict):
        final_message = response["modelResponse"].get("message")
        if final_message:
            result["token"] = Utils.safe_filter_grok_tags(final_message)
            result["type"] = 'content'
        return result

    # 规则 3：白名单 - “小总结”和“搜索结果” (只适用于 Agent 模型)
    AGENT_MODELS = ['grok-4', 'grok-3-deepersearch', 'grok-3-deepsearch']
    if model in AGENT_MODELS:
        THINKING_TAGS = {'header', 'summary', 'raw_function_result', 'citedWebSearchResults'}
        if message_tag in THINKING_TAGS:
            content_to_filter = None
            if token: content_to_filter = token
            elif response.get('webSearchResults') and CONFIG["ISSHOW_SEARCH_RESULTS"]:
                content_to_filter = Utils.organize_search_results(response['webSearchResults'])
            
            if content_to_filter:
                filtered_content = Utils.safe_filter_grok_tags(content_to_filter)
                if filtered_content:
                    result["token"] = filtered_content
                    result["type"] = 'thinking'
            return result

    # 规则 4：内心独白过滤 (只适用于 Agent 模型)
    if model in AGENT_MODELS:
        is_verbose_thinking = (response.get("isThinking") or response.get("messageStepId")) and message_tag not in {'header', 'summary'}
        if is_verbose_thinking:
            if not CONFIG["SHOW_THINKING"]:
                result["type"] = 'heartbeat' # 转换为心跳
                return result
            elif token:
                filtered_token = Utils.safe_filter_grok_tags(token)
                if filtered_token:
                    result["token"] = filtered_token
                    result["type"] = 'thinking'
            return result
    
    # 规则 5：对于非 Agent 模型，我们仍然需要处理它们的 token 流
    if model not in AGENT_MODELS and token:
        result["token"] = Utils.safe_filter_grok_tags(token)
        result["type"] = 'content'
        return result

    # 对于所有其他情况（特别是 Agent 模型的零散 final/assistant 块），
    # 我们返回一个空 result，实现静默丢弃。
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
    try:
        logger.info("开始处理非流式响应", "Server")

        stream = response.iter_lines()
        full_response = ""

        CONFIG["IS_THINKING"] = False
        CONFIG["IS_IMG_GEN"] = False
        CONFIG["IS_IMG_GEN2"] = False

        for chunk in stream:
            if not chunk:
                continue
            try:
                line_json = json.loads(chunk.decode("utf-8").strip())
                if line_json.get("error"):
                    logger.error(json.dumps(line_json, indent=2), "Server")
                    return json.dumps({"error": "RateLimitError"}) + "\n\n"

                response_data = line_json.get("result", {}).get("response")
                if not response_data:
                    continue

                if response_data.get("doImgGen") or response_data.get("imageAttachmentInfo"):
                    CONFIG["IS_IMG_GEN"] = True

                result = process_model_response(response_data, model)

                if result["token"]:
                    full_response += result["token"]

                if result["imageUrl"]:
                    CONFIG["IS_IMG_GEN2"] = True
                    return handle_image_response(result["imageUrl"])

            except json.JSONDecodeError:
                continue
            except Exception as e:
                logger.error(f"处理流式响应行时出错: {str(e)}", "Server")
                continue

        return full_response
    except Exception as error:
        logger.error(str(error), "Server")
        raise
# =======================================================================================
# =================== handle_stream_response (V23 - 最终分流版) ===================
# =======================================================================================
def handle_stream_response(response, model):
    
    AGENT_MODELS = ['grok-4', 'grok-3-deepersearch', 'grok-3-deepsearch']

    # ================= 分支 A: Agent 模型的专用处理逻辑 =================
    if model in AGENT_MODELS:
        def generate_agent():
            logger.info(f"使用 Agent 模型专用逻辑处理: {model}", "Server")
            stream = response.iter_lines()
            
            is_in_think_block = False
            final_answer_started = False

            # Agent 模型的内部辅助函数
            def yield_agent_content(content_to_yield, content_type='content'):
                nonlocal is_in_think_block
                is_thinking_content = content_type == 'thinking'

                if is_thinking_content and not is_in_think_block:
                    is_in_think_block = True
                    payload = MessageProcessor.create_chat_response('<think>', model, True)
                    yield f"data: {json.dumps(payload)}\n\n"
                
                elif not is_thinking_content and is_in_think_block:
                    is_in_think_block = False
                    payload = MessageProcessor.create_chat_response('</think>\n\n', model, True)
                    json_payload = json.dumps(payload)
                    yield f"data: {json_payload}\n\n"

                if is_thinking_content and content_to_yield:
                    content_to_yield = "\n" + content_to_yield

                if content_to_yield:
                    payload = MessageProcessor.create_chat_response(content_to_yield, model, True)
                    yield f"data: {json.dumps(payload)}\n\n"

            for chunk in stream:
                if not chunk: continue
                try:
                    line_json = json.loads(chunk.decode("utf-8").strip())
                    if line_json.get("error"): continue

                    response_data = line_json.get("result", {}).get("response")
                    if not response_data: continue
                    
                    # 优先处理最终答案块
                    if response_data.get("modelResponse") and isinstance(response_data["modelResponse"], dict):
                        final_answer_started = True
                        for part in yield_agent_content(None, content_type='content'): # 确保闭合<think>
                            yield part
                        
                        final_message = response_data["modelResponse"].get("message")
                        if final_message:
                            clean_message = Utils.safe_filter_grok_tags(final_message)
                            payload = MessageProcessor.create_chat_response(clean_message, model, True)
                            yield f"data: {json.dumps(payload)}\n\n"
                        break

                    # 处理思考过程和心跳
                    result = process_model_response(response_data, model)
                    if result.get("type") == 'heartbeat':
                        yield ":ping\n\n"
                    elif result.get("type") == 'thinking':
                        for part in yield_agent_content(result.get("token"), content_type='thinking'):
                            yield part

                except Exception as e:
                    logger.error(f"处理 Agent 流时出错: {str(e)}", "Server")
                    continue
            
            if is_in_think_block and not final_answer_started:
                payload = MessageProcessor.create_chat_response('</think>\n\n', model, True)
                json_payload = json.dumps(payload)
                yield f"data: {json_payload}\n\n"

            yield "data: [DONE]\n\n"
        return generate_agent()

    # ================= 分支 B: 标准模型的简单“直通车”逻辑 =================
    else:
        def generate_standard():
            logger.info(f"使用标准模型“无损直通车”逻辑处理: {model}", "Server")
            stream = response.iter_lines()

            for chunk in stream:
                if not chunk: continue
                try:
                    line_json = json.loads(chunk.decode("utf-8").strip())
                    if line_json.get("error"): continue

                    response_data = line_json.get("result", {}).get("response")
                    if not response_data: continue

                    # 对标准模型，我们只关心 token
                    token = response_data.get("token")
                    
                    # 关键修复：不再调用任何可能改变 token 的过滤函数！
                    # 我们相信标准模型的 token 是干净的。
                    if isinstance(token, str):
                        payload = MessageProcessor.create_chat_response(token, model, True)
                        yield f"data: {json.dumps(payload)}\n\n"

                except Exception as e:
                    logger.error(f"处理标准流时出错: {str(e)}", "Server")
                    continue

            yield "data: [DONE]\n\n"
        return generate_standard()
def initialization():
    sso_array = os.environ.get("SSO", "").split(',')
    logger.info("开始加载令牌", "Server")
    token_manager.load_token_status()
    for sso in sso_array:
        if sso:
            token_manager.add_token(f"sso-rw={sso};sso={sso}",True)
    token_manager.save_token_status()

    logger.info(f"成功加载令牌: {json.dumps(token_manager.get_all_tokens(), indent=2)}", "Server")
    logger.info(f"令牌加载完成，共加载: {len(token_manager.get_all_tokens())}个令牌", "Server")

    if CONFIG["API"]["PROXY"]:
        logger.info(f"代理已设置: {CONFIG['API']['PROXY']}", "Server")

logger.info("初始化完成", "Server")


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

@app.route('/v1/chat/completions', methods=['POST'])
def chat_completions():
    response_status_code = 500
    try:
        auth_token = request.headers.get('Authorization',
                                         '').replace('Bearer ', '')
        if auth_token:
            if CONFIG["API"]["IS_CUSTOM_SSO"]:
                result = f"sso={auth_token};sso-rw={auth_token}"
                token_manager.set_token(result)
            elif auth_token != CONFIG["API"]["API_KEY"]:
                return jsonify({"error": 'Unauthorized'}), 401
        else:
            return jsonify({"error": 'API_KEY缺失'}), 401

        data = request.json
        model = data.get("model")
        stream = data.get("stream", False)

        retry_count = 0
        grok_client = GrokApiClient(model)
        request_payload = grok_client.prepare_chat_request(data)
        logger.info(json.dumps(request_payload,indent=2))

        while retry_count < CONFIG["RETRY"]["MAX_ATTEMPTS"]:
            retry_count += 1
            CONFIG["API"]["SIGNATURE_COOKIE"] = Utils.create_auth_headers(model)

            if not CONFIG["API"]["SIGNATURE_COOKIE"]:
                raise ValueError('该模型无可用令牌')

            logger.info(
                f"当前令牌: {json.dumps(CONFIG['API']['SIGNATURE_COOKIE'], indent=2)}","Server")
            logger.info(
                f"当前可用模型的全部可用数量: {json.dumps(token_manager.get_remaining_token_request_capacity(), indent=2)}","Server")
            
            if CONFIG['SERVER']['CF_CLEARANCE']:
                CONFIG["SERVER"]['COOKIE'] = f"{CONFIG['API']['SIGNATURE_COOKIE']};{CONFIG['SERVER']['CF_CLEARANCE']}" 
            else:
                CONFIG["SERVER"]['COOKIE'] = CONFIG['API']['SIGNATURE_COOKIE']
            logger.info(json.dumps(request_payload,indent=2),"Server")
            try:
                proxy_options = Utils.get_proxy_options()

                # 使用智能重试机制发起请求
                def make_grok_request(**request_kwargs):
                    return curl_requests.post(
                        f"{CONFIG['API']['BASE_URL']}/rest/app-chat/conversations/new",
                        data=json.dumps(request_payload),
                        impersonate="chrome133a",
                        stream=True,
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
                logger.info(CONFIG["SERVER"]['COOKIE'],"Server")
                if response.status_code == 200:
                    response_status_code = 200
                    logger.info("请求成功", "Server")
                    logger.info(f"当前{model}剩余可用令牌数: {token_manager.get_token_count_for_model(model)}","Server")

                    try:
                        if stream:
                            return Response(stream_with_context(
                                handle_stream_response(response, model)),content_type='text/event-stream')
                        else:
                            content = handle_non_stream_response(response, model)
                            return jsonify(
                                MessageProcessor.create_chat_response(content, model))

                    except Exception as error:
                        logger.error(str(error), "Server")
                        if CONFIG["API"]["IS_CUSTOM_SSO"]:
                            raise ValueError(f"自定义SSO令牌当前模型{model}的请求次数已失效")
                        token_manager.remove_token_from_model(model, CONFIG["API"]["SIGNATURE_COOKIE"])
                        if token_manager.get_token_count_for_model(model) == 0:
                            raise ValueError(f"{model} 次数已达上限，请切换其他模型或者重新对话")
                elif response.status_code == 403:
                    response_status_code = 403
                    token_manager.reduce_token_request_count(model,1)#重置去除当前因为错误未成功请求的次数，确保不会因为错误未成功请求的次数导致次数上限
                    if token_manager.get_token_count_for_model(model) == 0:
                        raise ValueError(f"{model} 次数已达上限，请切换其他模型或者重新对话")
                    print("状态码:", response.status_code)
                    print("响应头:", response.headers)
                    print("响应内容:", response.text)
                    raise ValueError(f"IP暂时被封无法破盾，请稍后重试或者更换ip")
                elif response.status_code == 429:
                    response_status_code = 429
                    token_manager.reduce_token_request_count(model,1)
                    if CONFIG["API"]["IS_CUSTOM_SSO"]:
                        raise ValueError(f"自定义SSO令牌当前模型{model}的请求次数已失效")

                    token_manager.remove_token_from_model(
                        model, CONFIG["API"]["SIGNATURE_COOKIE"])
                    if token_manager.get_token_count_for_model(model) == 0:
                        raise ValueError(f"{model} 次数已达上限，请切换其他模型或者重新对话")

                else:
                    if CONFIG["API"]["IS_CUSTOM_SSO"]:
                        raise ValueError(f"自定义SSO令牌当前模型{model}的请求次数已失效")

                    logger.error(f"令牌异常错误状态!status: {response.status_code}","Server")
                    token_manager.remove_token_from_model(model, CONFIG["API"]["SIGNATURE_COOKIE"])
                    logger.info(
                        f"当前{model}剩余可用令牌数: {token_manager.get_token_count_for_model(model)}",
                        "Server")

            except Exception as e:
                logger.error(f"请求处理异常: {str(e)}", "Server")
                if CONFIG["API"]["IS_CUSTOM_SSO"]:
                    raise
                continue
        if response_status_code == 403:
            raise ValueError('IP暂时被封无法破盾，请稍后重试或者更换ip')
        elif response_status_code == 500:
            raise ValueError('当前模型所有令牌暂无可用，请稍后重试')    

    except Exception as error:
        logger.error(str(error), "ChatAPI")
        return jsonify(
            {"error": {
                "message": str(error),
                "type": "server_error"
            }}), response_status_code

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
