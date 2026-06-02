"""
API 路由工具函数

包含通用的日志记录、错误处理等辅助函数
"""

import logging
import traceback
from collections.abc import Mapping, Sequence

logger = logging.getLogger(__name__)

SENSITIVE_KEY_PARTS = (
    "api_key",
    "apikey",
    "authorization",
    "auth_token",
    "bearer",
    "password",
    "secret",
    "token",
)


def _safe_log_value(key: str, value):
    key_lower = str(key).lower()
    if any(part in key_lower for part in SENSITIVE_KEY_PARTS):
        return "[REDACTED]"
    if isinstance(value, bytes):
        return f"[{len(value)} bytes]"
    if isinstance(value, str):
        return value if len(value) <= 200 else f"{value[:200]}..."
    if isinstance(value, Mapping):
        return {
            str(child_key): _safe_log_value(str(child_key), child_value)
            for child_key, child_value in value.items()
        }
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [
            _safe_log_value(key, item)
            for item in list(value)[:20]
        ]
    return value


def log_request(endpoint: str, data: dict = None):
    """
    记录 API 请求日志

    Args:
        endpoint: API 端点路径
        data: 请求数据（会过滤敏感信息）
    """
    logger.info(f"📥 收到请求: {endpoint}")

    if data:
        # 过滤敏感信息和大数据（图片二进制）
        safe_data = {}
        for k, v in data.items():
            if k in ['images', 'user_images']:
                continue
            safe_data[k] = _safe_log_value(str(k), v)

        # 对图片数据只显示数量
        if 'images' in data:
            safe_data['images'] = f"[{len(data['images'])} 张图片]"
        if 'user_images' in data:
            safe_data['user_images'] = f"[{len(data['user_images'])} 张图片]"

        logger.debug(f"  请求数据: {safe_data}")


def log_error(endpoint: str, error: Exception):
    """
    记录 API 错误日志

    Args:
        endpoint: API 端点路径
        error: 异常对象
    """
    logger.error(f"❌ 请求失败: {endpoint}")
    logger.error(f"  错误类型: {type(error).__name__}")
    logger.error(f"  错误信息: {str(error)}")
    logger.debug(f"  堆栈跟踪:\n{traceback.format_exc()}")


def mask_api_key(key: str) -> str:
    """
    遮盖 API Key，只显示前4位和后4位

    Args:
        key: 原始 API Key

    Returns:
        str: 遮盖后的 API Key
    """
    if not key:
        return ''
    if len(key) <= 8:
        return '*' * len(key)
    return key[:4] + '*' * (len(key) - 8) + key[-4:]


def prepare_providers_for_response(providers: dict) -> dict:
    """
    准备返回给前端的 providers 数据

    将 api_key 替换为脱敏版本，避免泄露

    Args:
        providers: 原始服务商配置字典

    Returns:
        dict: 处理后的服务商配置
    """
    result = {}
    for name, config in providers.items():
        provider_copy = config.copy()

        # 返回脱敏的 api_key
        if 'api_key' in provider_copy and provider_copy['api_key']:
            provider_copy['api_key_masked'] = mask_api_key(provider_copy['api_key'])
            # 不返回实际值，前端用空字符串表示"不修改"
            provider_copy['api_key'] = ''
        else:
            provider_copy['api_key_masked'] = ''
            provider_copy['api_key'] = ''

        result[name] = provider_copy

    return result
