import logging
import os
import threading
import copy
import yaml
from pathlib import Path
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).parent.parent
TEXT_PROVIDER_TYPES = {"google_gemini", "openai_compatible"}
IMAGE_PROVIDER_TYPES = {"google_genai", "image_api", "openai_compatible"}


def _validate_base_url_syntax(value: str, *, field: str) -> str:
    base_url = value.strip()
    if not base_url:
        raise ValueError(f"{field} 不能为空字符串")
    if any(ord(ch) < 32 or ch.isspace() for ch in base_url):
        raise ValueError(f"{field} 不允许包含空白或控制字符")
    if len(base_url) > 2048:
        raise ValueError(f"{field} 长度过长")

    parsed = urlparse(base_url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise ValueError(f"{field} 必须是 http/https URL")
    if parsed.username or parsed.password:
        raise ValueError(f"{field} 不允许包含用户名或密码")

    return base_url


def _normalize_endpoint_path(value, *, field: str) -> str | None:
    if value in ("", None):
        return None
    if not isinstance(value, str):
        raise ValueError(f"{field} 必须是字符串")

    endpoint = value.strip()
    if not endpoint:
        return None
    if any(ord(ch) < 32 or ch.isspace() for ch in endpoint):
        raise ValueError(f"{field} 不允许包含空白或控制字符")
    if endpoint.startswith(("http://", "https://", "//")):
        raise ValueError(f"{field} 必须是 URL path，不能是完整 URL")
    if not endpoint.startswith("/"):
        endpoint = "/" + endpoint
    if len(endpoint) > 256:
        raise ValueError(f"{field} 长度过长")

    return endpoint


def _config_path_from_env(env_name: str, default_name: str) -> Path:
    raw = os.environ.get(env_name)
    if raw:
        return Path(raw)
    return PROJECT_ROOT / default_name


def _cors_origins_from_env() -> list[str]:
    return [
        origin.strip()
        for origin in os.environ.get(
            'REDINK_CORS_ORIGINS',
            'http://localhost:5173,http://localhost:3000'
        ).split(',')
        if origin.strip()
    ]


def _env_int(name: str, default: int, *, min_value: int | None = None, max_value: int | None = None) -> int:
    raw = os.environ.get(name)
    try:
        value = int(raw) if raw is not None else default
    except (TypeError, ValueError):
        logger.warning(f"环境变量 {name} 不是有效整数，使用默认值: {default}")
        value = default

    if min_value is not None and value < min_value:
        logger.warning(f"环境变量 {name} 小于最小值 {min_value}，使用默认值: {default}")
        return default
    if max_value is not None and value > max_value:
        logger.warning(f"环境变量 {name} 大于最大值 {max_value}，使用默认值: {default}")
        return default
    return value


class Config:
    DEBUG = os.environ.get('REDINK_DEBUG', 'false').lower() in ('true', '1', 'yes')
    # Default local/manual starts to loopback. Docker sets REDINK_HOST=0.0.0.0 explicitly.
    HOST = os.environ.get('REDINK_HOST', '127.0.0.1')
    PORT = _env_int('REDINK_PORT', 12398, min_value=1, max_value=65535)

    # Request size limits (bytes). Flask will reject larger bodies with 413.
    MAX_CONTENT_LENGTH = _env_int('REDINK_MAX_CONTENT_LENGTH', 32 * 1024 * 1024, min_value=1)

    # Base64 image input limits (applies to JSON base64 image arrays).
    MAX_BASE64_IMAGES = _env_int('REDINK_MAX_BASE64_IMAGES', 8, min_value=0)
    MAX_BASE64_IMAGE_BYTES = _env_int('REDINK_MAX_BASE64_IMAGE_BYTES', 10 * 1024 * 1024, min_value=1)
    MAX_BASE64_TOTAL_BYTES = _env_int('REDINK_MAX_BASE64_TOTAL_BYTES', 24 * 1024 * 1024, min_value=1)

    # History ZIP download preflight limit. Archives are built in memory.
    MAX_HISTORY_ZIP_SOURCE_BYTES = _env_int(
        'REDINK_MAX_HISTORY_ZIP_SOURCE_BYTES',
        256 * 1024 * 1024,
        min_value=1
    )
    CORS_ORIGINS = _cors_origins_from_env()
    _image_providers_config = None
    _text_providers_config = None
    _lock = threading.RLock()

    @staticmethod
    def get_text_providers_path() -> Path:
        return _config_path_from_env('REDINK_TEXT_PROVIDERS_PATH', 'text_providers.yaml')

    @staticmethod
    def get_image_providers_path() -> Path:
        return _config_path_from_env('REDINK_IMAGE_PROVIDERS_PATH', 'image_providers.yaml')

    @staticmethod
    def get_cors_origins() -> list[str]:
        return _cors_origins_from_env()

    @classmethod
    def validate_provider_config_paths(cls) -> None:
        """Reject text/image provider config paths that resolve to the same file."""
        text_path = cls.get_text_providers_path()
        image_path = cls.get_image_providers_path()
        try:
            same_path = text_path.resolve() == image_path.resolve()
        except Exception:
            same_path = text_path.absolute() == image_path.absolute()

        if same_path:
            raise ValueError(
                "REDINK_TEXT_PROVIDERS_PATH 和 REDINK_IMAGE_PROVIDERS_PATH 不能指向同一个文件，"
                "否则保存配置时会互相覆盖。请分别使用 text_providers.yaml 和 image_providers.yaml。"
            )

    @staticmethod
    def _validate_provider_config_shape(config, filename: str, *, allowed_types: set[str] | None = None) -> dict:
        if not isinstance(config, dict):
            raise ValueError(f"配置文件格式错误: {filename} 顶层必须是对象")

        active_provider = config.get('active_provider')
        if active_provider is not None and not isinstance(active_provider, str):
            raise ValueError(f"配置文件格式错误: {filename} active_provider 必须是字符串")

        providers = config.get('providers', {})
        if not isinstance(providers, dict):
            raise ValueError(f"配置文件格式错误: {filename} providers 必须是对象")

        for name, provider_config in providers.items():
            if not isinstance(name, str) or not name:
                raise ValueError(f"配置文件格式错误: {filename} 服务商名称必须是非空字符串")
            if not isinstance(provider_config, dict):
                raise ValueError(f"配置文件格式错误: {filename} 服务商配置必须是对象: {name}")
            provider_type = provider_config.get("type")
            if provider_type is not None:
                if not isinstance(provider_type, str) or not provider_type.strip():
                    raise ValueError(f"配置文件格式错误: {filename} 服务商类型必须是非空字符串: {name}")
                provider_type = provider_type.strip()
                provider_config["type"] = provider_type
            else:
                # Legacy configs may omit type and rely on provider name as the
                # effective generator/client type. Validate that fallback too.
                provider_type = name

            if allowed_types is not None and provider_type not in allowed_types:
                allowed = ", ".join(sorted(allowed_types))
                raise ValueError(
                    f"配置文件格式错误: {filename} 服务商类型不支持: {provider_type}（允许: {allowed}）"
                )

            if 'base_url' in provider_config:
                base_url = provider_config.get('base_url')
                if base_url in ("", None):
                    provider_config.pop('base_url', None)
                elif not isinstance(base_url, str):
                    raise ValueError(f"配置文件格式错误: {filename} {name}.base_url 必须是字符串")
                else:
                    provider_config['base_url'] = _validate_base_url_syntax(
                        base_url,
                        field=f"{name}.base_url",
                    )

            if 'endpoint_type' in provider_config:
                endpoint = _normalize_endpoint_path(
                    provider_config.get('endpoint_type'),
                    field=f"{name}.endpoint_type",
                )
                if endpoint:
                    provider_config['endpoint_type'] = endpoint
                else:
                    provider_config.pop('endpoint_type', None)

        if not active_provider and providers:
            config['active_provider'] = next(iter(providers))
            active_provider = config['active_provider']

        if active_provider and providers and active_provider not in providers:
            raise ValueError(f"配置文件格式错误: {filename} active_provider 不存在于 providers: {active_provider}")

        return config

    @classmethod
    def load_image_providers_config(cls):
        with cls._lock:
            if cls._image_providers_config is not None:
                return cls._image_providers_config

            config_path = cls.get_image_providers_path()
            logger.debug(f"加载图片服务商配置: {config_path}")

            if not config_path.exists():
                logger.warning(f"图片配置文件不存在: {config_path}，使用默认配置")
                cls._image_providers_config = {
                    'active_provider': 'google_genai',
                    'providers': {}
                }
                return cls._image_providers_config

            try:
                with open(config_path, 'r', encoding='utf-8') as f:
                    config = yaml.safe_load(f) or {}
                cls._image_providers_config = cls._validate_provider_config_shape(
                    config,
                    'image_providers.yaml',
                    allowed_types=IMAGE_PROVIDER_TYPES,
                )
                logger.debug(f"图片配置加载成功: {list(cls._image_providers_config.get('providers', {}).keys())}")
            except yaml.YAMLError as e:
                logger.error(f"图片配置文件 YAML 格式错误: {e}")
                raise ValueError(
                    f"配置文件格式错误: image_providers.yaml\n"
                    f"YAML 解析错误: {e}\n"
                    "解决方案：\n"
                    "1. 检查 YAML 缩进是否正确（使用空格，不要用Tab）\n"
                    "2. 检查引号是否配对\n"
                    "3. 使用在线 YAML 验证器检查格式"
                )

            return cls._image_providers_config

    @classmethod
    def load_text_providers_config(cls):
        """加载文本生成服务商配置"""
        with cls._lock:
            if cls._text_providers_config is not None:
                return cls._text_providers_config

            config_path = cls.get_text_providers_path()
            logger.debug(f"加载文本服务商配置: {config_path}")

            if not config_path.exists():
                logger.warning(f"文本配置文件不存在: {config_path}，使用默认配置")
                cls._text_providers_config = {
                    'active_provider': 'google_gemini',
                    'providers': {}
                }
                return cls._text_providers_config

            try:
                with open(config_path, 'r', encoding='utf-8') as f:
                    config = yaml.safe_load(f) or {}
                cls._text_providers_config = cls._validate_provider_config_shape(
                    config,
                    'text_providers.yaml',
                    allowed_types=TEXT_PROVIDER_TYPES,
                )
                logger.debug(f"文本配置加载成功: {list(cls._text_providers_config.get('providers', {}).keys())}")
            except yaml.YAMLError as e:
                logger.error(f"文本配置文件 YAML 格式错误: {e}")
                raise ValueError(
                    f"配置文件格式错误: text_providers.yaml\n"
                    f"YAML 解析错误: {e}\n"
                    "解决方案：\n"
                    "1. 检查 YAML 缩进是否正确（使用空格，不要用Tab）\n"
                    "2. 检查引号是否配对\n"
                    "3. 使用在线 YAML 验证器检查格式"
                )

            return cls._text_providers_config

    @classmethod
    def get_active_text_provider(cls):
        config = cls.load_text_providers_config()
        active = config.get('active_provider', 'google_gemini')
        logger.debug(f"当前激活的文本服务商: {active}")
        return active

    @classmethod
    def get_text_provider_config(cls, provider_name: str = None):
        """
        获取并验证文本服务商配置

        Args:
            provider_name: 服务商名称；不传则读取 active_provider
        """
        with cls._lock:
            config = cls.load_text_providers_config()
            if provider_name is None:
                provider_name = config.get('active_provider', 'google_gemini')

        logger.info(f"获取文本服务商配置: {provider_name}")

        providers = config.get('providers', {})
        if not providers:
            raise ValueError(
                "未找到任何文本生成服务商配置。\n"
                "解决方案：\n"
                "1. 在系统设置页面添加文本生成服务商\n"
                "2. 或手动编辑 text_providers.yaml 文件\n"
                "3. 确保文件中有 providers 字段"
            )

        if provider_name not in providers:
            available = ', '.join(providers.keys()) if providers else '无'
            logger.error(f"文本服务商 [{provider_name}] 不存在，可用服务商: {available}")
            raise ValueError(
                f"未找到文本生成服务商配置: {provider_name}\n"
                f"可用的服务商: {available}\n"
                "解决方案：\n"
                "1. 在系统设置页面添加该服务商\n"
                "2. 或修改 active_provider 为已存在的服务商\n"
                "3. 检查 text_providers.yaml 文件"
            )

        provider_config = copy.deepcopy(providers[provider_name])

        if not provider_config.get('api_key'):
            logger.error(f"文本服务商 [{provider_name}] 未配置 API Key")
            raise ValueError(
                f"服务商 {provider_name} 未配置 API Key\n"
                "解决方案：\n"
                "1. 在系统设置页面编辑该服务商，填写 API Key\n"
                "2. 或手动在 text_providers.yaml 中添加 api_key 字段"
            )

        provider_type = provider_config.get('type', provider_name)
        # OpenAI-compatible 文本需要 base_url（默认 openai 官方也可配置）
        if provider_type in ['openai', 'openai_compatible']:
            if not provider_config.get('base_url'):
                logger.error(f"文本服务商 [{provider_name}] 类型为 {provider_type}，但未配置 base_url")
                raise ValueError(
                    f"服务商 {provider_name} 未配置 Base URL\n"
                    f"服务商类型 {provider_type} 需要配置 base_url\n"
                    "解决方案：在系统设置页面编辑该服务商，填写 Base URL"
                )

        logger.info(f"文本服务商配置验证通过: {provider_name} (type={provider_type})")
        return provider_config

    @classmethod
    def get_active_image_provider(cls):
        config = cls.load_image_providers_config()
        active = config.get('active_provider', 'google_genai')
        logger.debug(f"当前激活的图片服务商: {active}")
        return active

    @classmethod
    def get_image_provider_config(cls, provider_name: str = None):
        with cls._lock:
            config = cls.load_image_providers_config()
            if provider_name is None:
                provider_name = config.get('active_provider', 'google_genai')

        logger.info(f"获取图片服务商配置: {provider_name}")

        providers = config.get('providers', {})
        if not providers:
            raise ValueError(
                "未找到任何图片生成服务商配置。\n"
                "解决方案：\n"
                "1. 在系统设置页面添加图片生成服务商\n"
                "2. 或手动编辑 image_providers.yaml 文件\n"
                "3. 确保文件中有 providers 字段"
            )

        if provider_name not in providers:
            available = ', '.join(providers.keys()) if providers else '无'
            logger.error(f"图片服务商 [{provider_name}] 不存在，可用服务商: {available}")
            raise ValueError(
                f"未找到图片生成服务商配置: {provider_name}\n"
                f"可用的服务商: {available}\n"
                "解决方案：\n"
                "1. 在系统设置页面添加该服务商\n"
                "2. 或修改 active_provider 为已存在的服务商\n"
                "3. 检查 image_providers.yaml 文件"
            )

        provider_config = copy.deepcopy(providers[provider_name])

        # 验证必要字段
        if not provider_config.get('api_key'):
            logger.error(f"图片服务商 [{provider_name}] 未配置 API Key")
            raise ValueError(
                f"服务商 {provider_name} 未配置 API Key\n"
                "解决方案：\n"
                "1. 在系统设置页面编辑该服务商，填写 API Key\n"
                "2. 或手动在 image_providers.yaml 中添加 api_key 字段"
            )

        provider_type = provider_config.get('type', provider_name)
        if provider_type in ['openai', 'openai_compatible', 'image_api']:
            if not provider_config.get('base_url'):
                logger.error(f"服务商 [{provider_name}] 类型为 {provider_type}，但未配置 base_url")
                raise ValueError(
                    f"服务商 {provider_name} 未配置 Base URL\n"
                    f"服务商类型 {provider_type} 需要配置 base_url\n"
                    "解决方案：在系统设置页面编辑该服务商，填写 Base URL"
                )

        logger.info(f"图片服务商配置验证通过: {provider_name} (type={provider_type})")
        return provider_config

    @classmethod
    def reload_config(cls):
        """重新加载配置（清除缓存）"""
        logger.info("重新加载所有配置...")
        with cls._lock:
            cls._image_providers_config = None
            cls._text_providers_config = None
