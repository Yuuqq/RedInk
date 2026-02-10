import logging
import os
import sys
import ctypes
from logging.handlers import RotatingFileHandler
from pathlib import Path
from flask import Flask, send_from_directory
from flask import request as flask_request
from flask_cors import CORS
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from backend.config import Config
from backend.routes import register_routes


class SafeStreamHandler(logging.StreamHandler):
    """
    StreamHandler that won't crash on Windows consoles with non-UTF8 encodings.

    Some environments default to GBK/CP936; emoji in log messages can trigger
    UnicodeEncodeError and break app startup. This handler downgrades such
    errors to replacement characters.
    """

    def emit(self, record):
        # NOTE: logging.StreamHandler.emit() catches exceptions internally and
        # calls handleError(), which still prints "Logging error" under
        # logging.raiseExceptions. We implement our own emit() to avoid that.
        try:
            msg = self.format(record)
            stream = self.stream
            terminator = getattr(self, "terminator", "\n")

            try:
                stream.write(msg + terminator)
            except UnicodeEncodeError:
                enc = getattr(stream, "encoding", None) or "utf-8"
                data = (msg + terminator).encode(enc, errors="replace")
                if hasattr(stream, "buffer"):
                    stream.buffer.write(data)
                else:
                    stream.write(data.decode(enc, errors="replace"))

            self.flush()
        except Exception:
            self.handleError(record)


def _force_utf8_console():
    """
    Best-effort: force UTF-8 stdout/stderr on Windows to avoid GBK emoji crashes.

    - For cmd.exe/PowerShell legacy consoles, set codepage to 65001.
    - Reconfigure Python streams to UTF-8.

    If the host console/font doesn't support Unicode, output may still look odd,
    but the process won't crash on UnicodeEncodeError.
    """
    if os.name != "nt":
        return

    try:
        # Set Windows console codepage to UTF-8 (process-level).
        ctypes.windll.kernel32.SetConsoleOutputCP(65001)
        ctypes.windll.kernel32.SetConsoleCP(65001)
    except Exception:
        pass

    try:
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        if hasattr(sys.stderr, "reconfigure"):
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


def setup_logging():
    """配置日志系统"""
    _force_utf8_console()

    # 创建根日志器
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG)

    # 清除已有的处理器
    root_logger.handlers.clear()

    # 控制台处理器 - 详细格式
    # Use a safe handler to avoid UnicodeEncodeError on Windows consoles (GBK).
    console_handler = SafeStreamHandler(sys.stdout)
    console_handler.setLevel(logging.DEBUG)
    console_format = logging.Formatter(
        '\n%(asctime)s | %(levelname)-8s | %(name)s\n'
        '  └─ %(message)s',
        datefmt='%H:%M:%S'
    )
    console_handler.setFormatter(console_format)
    root_logger.addHandler(console_handler)

    # 文件日志（用于管理面板查看）
    try:
        project_root = Path(__file__).parent.parent
        log_dir = project_root / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        log_file = os.environ.get("REDINK_LOG_FILE") or str(log_dir / "redink.log")

        file_handler = RotatingFileHandler(
            log_file,
            maxBytes=int(os.environ.get("REDINK_LOG_MAX_BYTES", str(5 * 1024 * 1024))),  # 5MB
            backupCount=int(os.environ.get("REDINK_LOG_BACKUP_COUNT", "5")),
            encoding="utf-8"
        )
        file_handler.setLevel(logging.DEBUG)
        file_format = logging.Formatter(
            '%(asctime)s | %(levelname)-8s | %(name)s | %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        file_handler.setFormatter(file_format)
        root_logger.addHandler(file_handler)
        root_logger.debug(f"日志文件输出已启用: {log_file}")
    except Exception as e:
        # Don't crash startup if file logging can't be enabled.
        root_logger.warning(f"无法启用文件日志: {e}")

    # 设置各模块的日志级别
    logging.getLogger('backend').setLevel(logging.DEBUG)
    logging.getLogger('werkzeug').setLevel(logging.INFO)
    logging.getLogger('urllib3').setLevel(logging.WARNING)

    return root_logger


def create_app():
    # 设置日志
    logger = setup_logging()
    logger.info("🚀 正在启动 CSS Lab AI图文生成器...")

    # 检查是否存在前端构建产物（Docker 环境）
    frontend_dist = Path(__file__).parent.parent / 'frontend' / 'dist'
    if frontend_dist.exists():
        logger.info("📦 检测到前端构建产物，启用静态文件托管模式")
        app = Flask(
            __name__,
            static_folder=str(frontend_dist),
            static_url_path=''
        )
    else:
        logger.info("🔧 开发模式，前端请单独启动")
        app = Flask(__name__)

    app.config.from_object(Config)

    CORS(app, resources={
        r"/api/*": {
            "origins": Config.CORS_ORIGINS,
            "methods": ["GET", "POST", "PUT", "DELETE", "OPTIONS"],
            "allow_headers": ["Content-Type", "Authorization"],
        }
    })

    # Rate limiting
    limiter = Limiter(
        get_remote_address,
        app=app,
        default_limits=[
            os.environ.get('REDINK_RATE_LIMIT', '60 per minute')
        ],
        storage_uri="memory://",
    )
    app.limiter = limiter

    # 注册所有 API 路由
    register_routes(app)

    # 启动时验证配置
    _validate_config_on_startup(logger)

    # 根据是否有前端构建产物决定根路由行为
    if frontend_dist.exists():
        @app.route('/')
        def serve_index():
            return send_from_directory(app.static_folder, 'index.html')

        # 处理 Vue Router 的 HTML5 History 模式
        @app.errorhandler(404)
        def fallback(e):
            # Do not hijack API 404s, otherwise clients get HTML with 200.
            if flask_request.path.startswith('/api/'):
                return {"success": False, "error": "Not Found"}, 404
            return send_from_directory(app.static_folder, 'index.html')
    else:
        @app.route('/')
        def index():
            return {
                "message": "CSS Lab AI图文生成器 API",
                "version": "0.1.0",
                "endpoints": {
                    "health": "/api/health",
                    "outline": "POST /api/outline",
                    "generate": "POST /api/generate",
                    "images": "GET /api/images/<filename>"
                }
            }

    return app


def _validate_config_on_startup(logger):
    """启动时验证配置"""
    from pathlib import Path
    import yaml

    logger.info("📋 检查配置文件...")

    # 检查 text_providers.yaml
    text_config_path = Path(__file__).parent.parent / 'text_providers.yaml'
    if text_config_path.exists():
        try:
            with open(text_config_path, 'r', encoding='utf-8') as f:
                text_config = yaml.safe_load(f) or {}
            active = text_config.get('active_provider', '未设置')
            providers = list(text_config.get('providers', {}).keys())
            logger.info(f"✅ 文本生成配置: 激活={active}, 可用服务商={providers}")

            # 检查激活的服务商是否有 API Key
            if active in text_config.get('providers', {}):
                provider = text_config['providers'][active]
                if not provider.get('api_key'):
                    logger.warning(f"⚠️  文本服务商 [{active}] 未配置 API Key")
                else:
                    logger.info(f"✅ 文本服务商 [{active}] API Key 已配置")
        except Exception as e:
            logger.error(f"❌ 读取 text_providers.yaml 失败: {e}")
    else:
        logger.warning("⚠️  text_providers.yaml 不存在，将使用默认配置")

    # 检查 image_providers.yaml
    image_config_path = Path(__file__).parent.parent / 'image_providers.yaml'
    if image_config_path.exists():
        try:
            with open(image_config_path, 'r', encoding='utf-8') as f:
                image_config = yaml.safe_load(f) or {}
            active = image_config.get('active_provider', '未设置')
            providers = list(image_config.get('providers', {}).keys())
            logger.info(f"✅ 图片生成配置: 激活={active}, 可用服务商={providers}")

            # 检查激活的服务商是否有 API Key
            if active in image_config.get('providers', {}):
                provider = image_config['providers'][active]
                if not provider.get('api_key'):
                    logger.warning(f"⚠️  图片服务商 [{active}] 未配置 API Key")
                else:
                    logger.info(f"✅ 图片服务商 [{active}] API Key 已配置")
        except Exception as e:
            logger.error(f"❌ 读取 image_providers.yaml 失败: {e}")
    else:
        logger.warning("⚠️  image_providers.yaml 不存在，将使用默认配置")

    logger.info("✅ 配置检查完成")


if __name__ == '__main__':
    app = create_app()
    app.run(
        host=Config.HOST,
        port=Config.PORT,
        debug=Config.DEBUG
    )
