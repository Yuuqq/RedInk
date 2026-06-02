"""
配置管理相关 API 路由

包含功能：
- 获取当前配置
- 更新配置
- 测试服务商连接
"""

import logging
import os
import threading
import uuid
from pathlib import Path
import yaml
from flask import Blueprint, request, jsonify
from backend.config import (
    Config,
    IMAGE_PROVIDER_TYPES,
    TEXT_PROVIDER_TYPES,
    _normalize_endpoint_path,
    _validate_base_url_syntax,
)
from backend.middleware import require_auth
from backend.utils.url import normalize_openai_base_url
from backend.utils.remote_image import (
    allow_private_provider_urls,
    allow_unpinned_provider_urls,
    safe_http_request,
    validate_public_http_url,
)
from .utils import prepare_providers_for_response

logger = logging.getLogger(__name__)

# 配置文件路径
CONFIG_DIR = Path(__file__).parent.parent.parent
# Tests may monkeypatch these; when left as None, paths are resolved from env at call time.
IMAGE_CONFIG_PATH: Path | None = None
TEXT_CONFIG_PATH: Path | None = None
_CONFIG_WRITE_LOCK = threading.RLock()


def _image_config_path() -> Path:
    return IMAGE_CONFIG_PATH or Config.get_image_providers_path()


def _text_config_path() -> Path:
    return TEXT_CONFIG_PATH or Config.get_text_providers_path()


def _validate_effective_provider_config_paths() -> None:
    text_path = _text_config_path()
    image_path = _image_config_path()
    try:
        same_path = text_path.resolve() == image_path.resolve()
    except Exception:
        same_path = text_path.absolute() == image_path.absolute()

    if same_path:
        raise ValueError(
            "文本和图片服务商配置不能指向同一个文件，否则保存配置时会互相覆盖。"
            "请分别使用 text_providers.yaml 和 image_providers.yaml。"
        )


def create_config_blueprint():
    """创建配置路由蓝图（工厂函数，支持多次调用）"""
    config_bp = Blueprint('config', __name__)

    # ==================== 配置读写 ====================

    @config_bp.route('/config', methods=['GET'])
    @require_auth
    def get_config():
        """
        获取当前配置

        返回：
        - success: 是否成功
        - config: 配置对象
          - text_generation: 文本生成配置
          - image_generation: 图片生成配置
        """
        try:
            _validate_effective_provider_config_paths()
            # 读取图片生成配置
            image_config = _read_config(_image_config_path(), {
                'active_provider': 'google_genai',
                'providers': {}
            })

            # 读取文本生成配置
            text_config = _read_config(_text_config_path(), {
                'active_provider': 'google_gemini',
                'providers': {}
            })

            return jsonify({
                "success": True,
                "config": {
                    "text_generation": {
                        "active_provider": text_config.get('active_provider', ''),
                        "providers": prepare_providers_for_response(
                            text_config.get('providers', {})
                        )
                    },
                    "image_generation": {
                        "active_provider": image_config.get('active_provider', ''),
                        "providers": prepare_providers_for_response(
                            image_config.get('providers', {})
                        )
                    }
                }
            })

        except Exception as e:
            return jsonify({
                "success": False,
                "error": f"获取配置失败: {str(e)}"
            }), 500

    @config_bp.route('/config', methods=['POST'])
    @require_auth
    def update_config():
        """
        更新配置

        请求体：
        - image_generation: 图片生成配置（可选）
        - text_generation: 文本生成配置（可选）

        返回：
        - success: 是否成功
        - message: 结果消息
        """
        try:
            _validate_effective_provider_config_paths()
            data = request.get_json(silent=True)
            if not isinstance(data, dict):
                return jsonify({"success": False, "error": "请求体必须是 JSON object"}), 400

            _update_all_provider_configs(data)

            # 清除配置缓存，确保下次使用时读取新配置
            _clear_config_cache()

            return jsonify({
                "success": True,
                "message": "配置已保存"
            })

        except ValueError as e:
            return jsonify({
                "success": False,
                "error": str(e)
            }), 400
        except Exception as e:
            return jsonify({
                "success": False,
                "error": f"更新配置失败: {str(e)}"
            }), 500

    # ==================== 连接测试 ====================

    @config_bp.route('/config/test', methods=['POST'])
    @require_auth
    def test_connection():
        """
        测试服务商连接

        请求体：
        - type: 服务商类型（google_genai/google_gemini/openai_compatible/image_api）
        - provider_category: 服务商类别（text/image，用于区分 openai_compatible）
        - provider_name: 服务商名称（用于从配置读取 API Key）
        - api_key: API Key（可选，若不提供则从配置读取）
        - base_url: Base URL（可选）
        - model: 模型名称（可选）
        - endpoint_type: OpenAI 兼容端点路径（可选）

        返回：
        - success: 是否成功
        - message: 测试结果消息
        """
        try:
            _validate_effective_provider_config_paths()
            data = request.get_json(silent=True)
            if not isinstance(data, dict):
                return jsonify({"success": False, "error": "请求体必须是 JSON object"}), 400
            provider_type = data.get('type')
            provider_name = data.get('provider_name')
            provider_category = data.get('provider_category')

            if not provider_type:
                return jsonify({"success": False, "error": "缺少 type 参数"}), 400
            if provider_category is not None and provider_category not in ("text", "image"):
                return jsonify({"success": False, "error": "provider_category 只能为 text 或 image"}), 400

            # 构建配置
            config = {
                'api_key': data.get('api_key'),
                'base_url': data.get('base_url'),
                'model': data.get('model'),
                'endpoint_type': data.get('endpoint_type'),
            }

            # 如果没有提供 api_key，从配置文件读取
            if not config['api_key'] and provider_name:
                config = _load_provider_config(
                    provider_type,
                    provider_name,
                    config,
                    provider_category=provider_category,
                )

            if not config['api_key']:
                return jsonify({"success": False, "error": "API Key 未配置"}), 400

            # 根据类型执行测试
            result = _test_provider_connection(provider_type, config, provider_category=provider_category)
            return jsonify(result), 200 if result['success'] else 400

        except Exception as e:
            return jsonify({"success": False, "error": str(e)}), 400

    return config_bp


# ==================== 辅助函数 ====================

def _read_config(path: Path, default: dict) -> dict:
    """读取配置文件"""
    if path.exists():
        with open(path, 'r', encoding='utf-8') as f:
            config = yaml.safe_load(f) or default
        if not isinstance(config, dict):
            raise ValueError(f"配置文件格式错误：{path.name} 顶层必须是对象")
        if 'providers' in config and not isinstance(config.get('providers'), dict):
            raise ValueError(f"配置文件格式错误：{path.name} providers 必须是对象")
        return config
    return default


def _write_config(path: Path, config: dict):
    """写入配置文件"""
    # Atomic write: write to temp file then replace, to avoid corrupting config on crash.
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f".{path.name}.{os.getpid()}.{threading.get_ident()}.{uuid.uuid4().hex}.tmp")
    try:
        with open(tmp_path, 'w', encoding='utf-8', newline='\n') as f:
            yaml.dump(config, f, allow_unicode=True, default_flow_style=False, sort_keys=False)
        os.replace(tmp_path, path)
    finally:
        try:
            tmp_path.unlink(missing_ok=True)
        except Exception:
            pass


def _update_all_provider_configs(data: dict):
    """Validate all requested config sections before writing any file."""
    updates: list[tuple[Path, dict]] = []
    originals: dict[Path, dict] = {}

    with _CONFIG_WRITE_LOCK:
        _validate_effective_provider_config_paths()

        if 'image_generation' in data:
            image_path = _image_config_path()
            originals[image_path] = _read_config(image_path, {'providers': {}})
            updates.append((
                image_path,
                _build_updated_provider_config(
                    image_path,
                    data['image_generation'],
                    allowed_types=IMAGE_PROVIDER_TYPES,
                )
            ))

        if 'text_generation' in data:
            text_path = _text_config_path()
            originals[text_path] = _read_config(text_path, {'providers': {}})
            updates.append((
                text_path,
                _build_updated_provider_config(
                    text_path,
                    data['text_generation'],
                    allowed_types=TEXT_PROVIDER_TYPES,
                )
            ))

        written: list[Path] = []
        try:
            for path, config in updates:
                _write_config(path, config)
                written.append(path)
        except Exception:
            # Best-effort rollback keeps a multi-file save from leaving a mixed
            # image/text provider configuration if a later write fails.
            for path in reversed(written):
                try:
                    _write_config(path, originals[path])
                except Exception:
                    logger.exception("配置写入失败后回滚失败: %s", path)
            raise


def _update_provider_config(config_path: Path, new_data: dict, *, allowed_types: set[str] | None = None):
    """
    更新服务商配置

    Args:
        config_path: 配置文件路径
        new_data: 新的配置数据
    """
    with _CONFIG_WRITE_LOCK:
        _validate_effective_provider_config_paths()
        _write_config(
            config_path,
            _build_updated_provider_config(config_path, new_data, allowed_types=allowed_types),
        )


def _build_updated_provider_config(config_path: Path, new_data: dict, *, allowed_types: set[str] | None = None) -> dict:
    if not isinstance(new_data, dict):
        raise ValueError("配置段必须是 JSON object")

    # 读取现有配置
    existing_config = _read_config(config_path, {'providers': {}})

    # 更新 active_provider
    if 'active_provider' in new_data:
        if not isinstance(new_data['active_provider'], str):
            raise ValueError("active_provider 必须是字符串")
        existing_config['active_provider'] = new_data['active_provider']

    # 更新 providers
    if 'providers' in new_data:
        existing_providers = existing_config.get('providers', {})
        new_providers = new_data['providers']
        if not isinstance(new_providers, dict):
            raise ValueError("providers 必须是 JSON object")

        sanitized_providers = {}
        for name, new_provider_config in new_providers.items():
            if not isinstance(name, str) or not name:
                raise ValueError("服务商名称必须是非空字符串")
            if not isinstance(new_provider_config, dict):
                raise ValueError(f"服务商配置必须是 JSON object: {name}")
            provider_config = _sanitize_provider_config(
                name,
                new_provider_config,
                allowed_types=allowed_types,
            )
            # 如果新配置的 api_key 是空的，保留原有的
            if provider_config.get('api_key') in [True, False, '', None]:
                if name in existing_providers and existing_providers[name].get('api_key'):
                    provider_config['api_key'] = existing_providers[name]['api_key']
                else:
                    provider_config.pop('api_key', None)

            # 移除不需要保存的字段
            provider_config.pop('api_key_env', None)
            provider_config.pop('api_key_masked', None)
            sanitized_providers[name] = provider_config

        existing_config['providers'] = sanitized_providers

    active_provider = existing_config.get('active_provider')
    providers = existing_config.get('providers', {})
    if not active_provider and providers:
        existing_config['active_provider'] = next(iter(providers))
        active_provider = existing_config['active_provider']
    if active_provider and active_provider not in providers:
        raise ValueError(f"active_provider 不存在于 providers: {active_provider}")

    return existing_config


def _sanitize_provider_config(
    name: str,
    provider_config: dict,
    *,
    allowed_types: set[str] | None,
) -> dict:
    sanitized = dict(provider_config)

    provider_type = sanitized.get("type")
    if not isinstance(provider_type, str) or not provider_type.strip():
        raise ValueError(f"服务商类型必须是非空字符串: {name}")
    provider_type = provider_type.strip()
    if allowed_types is not None and provider_type not in allowed_types:
        allowed = ", ".join(sorted(allowed_types))
        raise ValueError(f"服务商类型不支持: {provider_type}（允许: {allowed}）")
    sanitized["type"] = provider_type

    for string_field in ("api_key", "model"):
        value = sanitized.get(string_field)
        if value is not None and value not in (True, False) and not isinstance(value, str):
            raise ValueError(f"{name}.{string_field} 必须是字符串")

    if "base_url" in sanitized:
        base_url = sanitized.get("base_url")
        if base_url in ("", None):
            sanitized.pop("base_url", None)
        elif not isinstance(base_url, str):
            raise ValueError(f"{name}.base_url 必须是字符串")
        else:
            sanitized["base_url"] = _validate_base_url_syntax(base_url, field=f"{name}.base_url")

    if "endpoint_type" in sanitized:
        endpoint = _normalize_endpoint_path(sanitized.get("endpoint_type"), field=f"{name}.endpoint_type")
        if endpoint:
            sanitized["endpoint_type"] = endpoint
        else:
            sanitized.pop("endpoint_type", None)

    for bool_field in ("high_concurrency", "short_prompt"):
        value = sanitized.get(bool_field)
        if value is not None and not isinstance(value, bool):
            raise ValueError(f"{name}.{bool_field} 必须是布尔值")

    return sanitized


def _clear_config_cache():
    """清除配置缓存"""
    try:
        from backend.config import Config
        Config.reload_config()
    except Exception:
        pass

    try:
        from backend.services.image import reset_image_service
        reset_image_service()
    except Exception:
        pass


def _load_provider_config(
    provider_type: str,
    provider_name: str,
    config: dict,
    *,
    provider_category: str | None = None,
) -> dict:
    """
    从配置文件加载服务商配置

    Args:
        provider_type: 服务商类型
        provider_name: 服务商名称
        config: 当前配置（会被合并）

    Returns:
        dict: 合并后的配置
    """
    # 确定配置文件路径。openai_compatible 同时支持文本和图片，
    # 所以优先使用前端传入的 provider_category 消除歧义。
    if provider_category == "text":
        config_path = _text_config_path()
    elif provider_category == "image":
        config_path = _image_config_path()
    elif provider_type in ['openai_compatible', 'google_gemini']:
        config_path = _text_config_path()
    else:
        config_path = _image_config_path()

    if config_path.exists():
        with open(config_path, 'r', encoding='utf-8') as f:
            yaml_config = yaml.safe_load(f) or {}
            providers = yaml_config.get('providers', {})

            if provider_name in providers:
                saved = providers[provider_name]
                config['api_key'] = saved.get('api_key')

                if not config['base_url']:
                    config['base_url'] = saved.get('base_url')
                if not config['model']:
                    config['model'] = saved.get('model')
                if not config.get('endpoint_type'):
                    config['endpoint_type'] = saved.get('endpoint_type')

    return config


def _test_provider_connection(provider_type: str, config: dict, *, provider_category: str | None = None) -> dict:
    """
    测试服务商连接

    Args:
        provider_type: 服务商类型
        config: 服务商配置

    Returns:
        dict: 测试结果
    """
    test_prompt = "请回复'你好，CSS Lab'"

    if provider_type == 'google_genai':
        return _test_google_genai(config)

    elif provider_type == 'google_gemini':
        return _test_google_gemini(config, test_prompt)

    elif provider_type == 'openai_compatible' and provider_category == 'image':
        return _test_image_api(config)

    elif provider_type == 'openai_compatible':
        return _test_openai_compatible(config, test_prompt)

    elif provider_type == 'image_api':
        return _test_image_api(config)

    else:
        raise ValueError(f"不支持的类型: {provider_type}")


def _test_google_genai(config: dict) -> dict:
    """测试 Google GenAI 图片生成服务"""
    from google import genai

    client_kwargs = {
        'api_key': config['api_key'],
        'vertexai': False
    }
    if config.get('base_url'):
        if not allow_unpinned_provider_urls():
            raise ValueError(
                "Google GenAI 自定义 Base URL 默认禁用。\n"
                "原因：Google SDK 管理底层 HTTP 连接，无法在本应用内固定已验证 IP，存在 DNS rebinding SSRF 风险。\n"
                "解决方案：留空 base_url 使用官方 Gemini API，或在可信内网部署时设置 REDINK_ALLOW_UNPINNED_PROVIDER_URLS=1。"
            )
        safe_base_url = validate_public_http_url(
            config['base_url'],
            label="服务商 Base URL",
            allow_private=allow_private_provider_urls(),
        )
        client_kwargs['http_options'] = {
            'base_url': safe_base_url,
            'api_version': 'v1beta'
        }

    client = genai.Client(**client_kwargs)
    # 测试列出模型。实际图片生成同样使用 API Key + vertexai=False。
    try:
        list(client.models.list())
        return {
            "success": True,
            "message": "连接成功！仅代表连接稳定，不确定是否可以稳定支持图片生成"
        }
    except Exception as e:
        raise Exception(f"连接测试失败: {str(e)}")


def _test_google_gemini(config: dict, test_prompt: str) -> dict:
    """测试 Google Gemini 文本生成服务"""
    from google import genai

    if config.get('base_url'):
        if not allow_unpinned_provider_urls():
            raise ValueError(
                "Google GenAI 自定义 Base URL 默认禁用。\n"
                "原因：Google SDK 管理底层 HTTP 连接，无法在本应用内固定已验证 IP，存在 DNS rebinding SSRF 风险。\n"
                "解决方案：留空 base_url 使用官方 Gemini API，或在可信内网部署时设置 REDINK_ALLOW_UNPINNED_PROVIDER_URLS=1。"
            )
        safe_base_url = validate_public_http_url(
            config['base_url'],
            label="服务商 Base URL",
            allow_private=allow_private_provider_urls(),
        )
        client = genai.Client(
            api_key=config['api_key'],
            http_options={
                'base_url': safe_base_url,
                'api_version': 'v1beta'
            },
            vertexai=False
        )
    else:
        client = genai.Client(
            api_key=config['api_key'],
            vertexai=False
        )

    model = config.get('model') or 'gemini-2.0-flash-exp'
    response = client.models.generate_content(
        model=model,
        contents=test_prompt
    )
    result_text = response.text if hasattr(response, 'text') else str(response)

    return _check_response(result_text)


def _test_openai_compatible(config: dict, test_prompt: str) -> dict:
    """测试 OpenAI 兼容接口"""
    return _test_chat_completion(config, test_prompt)


def _normalized_provider_base_url(config: dict) -> str:
    base_url = normalize_openai_base_url(config.get('base_url'), default='https://api.openai.com')
    return validate_public_http_url(
        base_url,
        label="服务商 Base URL",
        allow_private=allow_private_provider_urls(),
    )


def _endpoint_path(config: dict, default: str) -> str:
    endpoint = config.get('endpoint_type') or default
    if endpoint == 'images':
        endpoint = '/v1/images/generations'
    elif endpoint == 'chat':
        endpoint = '/v1/chat/completions'
    if not endpoint.startswith('/'):
        endpoint = '/' + endpoint
    return endpoint


def _is_chat_endpoint(config: dict) -> bool:
    endpoint = _endpoint_path(config, '/v1/images/generations').lower()
    return 'chat' in endpoint or 'completions' in endpoint


def _test_chat_completion(config: dict, test_prompt: str) -> dict:
    base_url = _normalized_provider_base_url(config)
    url = f"{base_url}{_endpoint_path(config, '/v1/chat/completions')}"

    payload = {
        "model": config.get('model') or 'gpt-3.5-turbo',
        "messages": [{"role": "user", "content": test_prompt}],
        "max_tokens": 50
    }

    response = safe_http_request(
        "POST",
        url,
        label="服务商 Base URL",
        allow_private=allow_private_provider_urls(),
        headers={
            'Authorization': f"Bearer {config['api_key']}",
            'Content-Type': 'application/json'
        },
        json=payload,
        timeout=30,
        allow_redirects=False,
    )

    if response.status_code != 200:
        raise Exception(f"HTTP {response.status_code}: {response.text[:200]}")

    result = response.json()
    result_text = result['choices'][0]['message']['content']

    return _check_response(result_text)


def _test_image_api(config: dict) -> dict:
    """测试图片 API 连接"""
    if _is_chat_endpoint(config):
        return _test_chat_completion(config, "请回复'你好，CSS Lab'")

    base_url = _normalized_provider_base_url(config)
    url = f"{base_url}/v1/models"

    response = safe_http_request(
        "GET",
        url,
        label="服务商 Base URL",
        allow_private=allow_private_provider_urls(),
        headers={'Authorization': f"Bearer {config['api_key']}"},
        timeout=30,
        allow_redirects=False,
    )

    if response.status_code == 200:
        return {
            "success": True,
            "message": "连接成功！仅代表连接稳定，不确定是否可以稳定支持图片生成"
        }
    else:
        raise Exception(f"HTTP {response.status_code}: {response.text[:200]}")


def _check_response(result_text: str) -> dict:
    """检查响应是否符合预期"""
    if "你好" in result_text and ("CSS Lab" in result_text or "CSSLAB" in result_text or "css lab" in result_text.lower()):
        return {
            "success": True,
            "message": f"连接成功！响应: {result_text[:100]}"
        }
    else:
        return {
            "success": True,
            "message": f"连接成功，但响应内容不符合预期: {result_text[:100]}"
        }
