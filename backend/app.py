import logging
import hmac
import os
import sys
import ctypes
import shutil
import time
from urllib.parse import unquote
from logging.handlers import RotatingFileHandler
from pathlib import Path
from flask import Flask, send_from_directory
from flask import request as flask_request
from flask_cors import CORS
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from backend.config import Config
from backend.routes import register_routes

IMAGE_AUTH_COOKIE = "redink_auth_token"


def _env_flag(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in ("1", "true", "yes")


def _env_int(name: str, default: int, *, min_value: int | None = None) -> int:
    raw = os.environ.get(name)
    try:
        value = int(raw) if raw is not None else default
    except (TypeError, ValueError):
        return default
    if min_value is not None and value < min_value:
        return default
    return value


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


class SafeRotatingFileHandler(RotatingFileHandler):
    """
    RotatingFileHandler with a Windows-safe rollover fallback.

    On Windows, another process can hold the log file and make os.rename()
    fail during automatic rollover. The default handler reports a "Logging
    error" traceback for every emit. Fall back to copy+truncate, matching the
    admin manual rotation behavior, so logging stays usable.
    """

    def doRollover(self):
        try:
            return super().doRollover()
        except OSError:
            self._copy_truncate_rollover()

    def _copy_truncate_rollover(self):
        if self.stream:
            try:
                self.stream.close()
            finally:
                self.stream = None

        try:
            if os.path.exists(self.baseFilename):
                ts = time.strftime("%Y%m%d-%H%M%S")
                backup_file = f"{self.baseFilename}.{ts}.bak"
                shutil.copyfile(self.baseFilename, backup_file)
                with open(self.baseFilename, "r+b") as f:
                    f.truncate(0)
        except Exception:
            # Suppress rollover failures to avoid recursive logging tracebacks.
            # The next writes still go to the original log file.
            pass
        finally:
            if not self.delay:
                self.stream = self._open()


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

    # 清除并关闭已有处理器，避免重复 create_app()/测试/重载时泄漏日志文件句柄。
    for handler in list(root_logger.handlers):
        root_logger.removeHandler(handler)
        try:
            handler.close()
        except Exception:
            pass

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

        file_handler = SafeRotatingFileHandler(
            log_file,
            maxBytes=_env_int("REDINK_LOG_MAX_BYTES", 5 * 1024 * 1024, min_value=1),
            backupCount=_env_int("REDINK_LOG_BACKUP_COUNT", 5, min_value=0),
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
    _validate_network_exposure_config(Config.HOST)
    Config.validate_provider_config_paths()

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

    @app.before_request
    def _reject_unauthenticated_remote_clients():
        """
        Runtime backstop for WSGI/process-manager deployments.

        Fail closed when no token is configured. Reverse proxies commonly send
        public traffic to gunicorn from 127.0.0.1, so request.remote_addr cannot
        safely prove that an unauthenticated request is local-only.
        """
        if (os.environ.get("REDINK_AUTH_TOKEN") or "").strip():
            return None
        if _env_flag("REDINK_ALLOW_UNAUTH_REMOTE"):
            return None

        return {
            "success": False,
            "error": (
                "拒绝未认证访问。请设置 REDINK_AUTH_TOKEN，"
                "或仅在明确受控环境中设置 REDINK_ALLOW_UNAUTH_REMOTE=1。"
            ),
        }, 403

    @app.before_request
    def _require_api_auth():
        """
        Optional API-wide auth guard.

        When REDINK_AUTH_TOKEN is set, require `Authorization: Bearer <token>` for most `/api/*` routes.
        Exemptions:
        - `/api/health` (used by health checks)
        - `/api/images/*` can use either Bearer auth or the same-site image auth cookie
        - `OPTIONS` (CORS preflight)
        """
        auth_token = (os.environ.get("REDINK_AUTH_TOKEN") or "").strip()
        if not auth_token:
            return None

        path = flask_request.path or ""
        if not path.startswith("/api/"):
            return None
        if flask_request.method == "OPTIONS":
            return None
        if path == "/api/health":
            return None
        if path.startswith("/api/images/"):
            if _request_has_valid_auth(auth_token, allow_image_cookie=True):
                return None
            return {
                "success": False,
                "error": "未提供认证令牌。请在系统设置中填写访问控制 Token 后重试。",
            }, 401

        if not _request_has_valid_auth(auth_token):
            return {
                "success": False,
                "error": "未提供认证令牌。请在请求头中添加 Authorization: Bearer <token>",
            }, 401

        return None

    @app.after_request
    def _add_security_headers(resp):
        # Safe, low-risk defaults. Consider adding CSP/HSTS at your reverse proxy.
        resp.headers.setdefault("X-Content-Type-Options", "nosniff")
        resp.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        return resp

    @app.errorhandler(413)
    def _request_too_large(_e):
        if flask_request.path.startswith("/api/"):
            return {"success": False, "error": "请求体过大（413）。请减少图片数量/大小或调大 REDINK_MAX_CONTENT_LENGTH。"}, 413
        return "Request Entity Too Large", 413

    CORS(app, resources={
        r"/api/*": {
            "origins": Config.get_cors_origins(),
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
        storage_uri=os.environ.get("REDINK_RATE_LIMIT_STORAGE_URI", "memory://"),
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
            path = flask_request.path or ""
            if path.startswith('/api/'):
                return {"success": False, "error": "Not Found"}, 404
            # Do not serve index.html for missing static assets; browsers would
            # otherwise receive HTML for JS/CSS/images and fail with MIME errors.
            if Path(path).suffix:
                return "Not Found", 404, {"Content-Type": "text/plain; charset=utf-8"}
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
                    "images": "GET /api/images/<task_id>/<filename>"
                }
            }

    return app


def _request_has_valid_auth(auth_token: str, *, allow_image_cookie: bool = False) -> bool:
    auth_header = flask_request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        token = auth_header[7:]
        if hmac.compare_digest(token, auth_token):
            return True

    if allow_image_cookie:
        cookie_token = flask_request.cookies.get(IMAGE_AUTH_COOKIE, "")
        if cookie_token and hmac.compare_digest(unquote(cookie_token), auth_token):
            return True

    return False


def _validate_config_on_startup(logger):
    """启动时验证配置"""
    logger.info("📋 检查配置文件...")

    # 检查 text_providers.yaml
    text_config_path = Config.get_text_providers_path()
    if text_config_path.exists():
        text_config = Config.load_text_providers_config()
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
    else:
        logger.warning("⚠️  text_providers.yaml 不存在，将使用默认配置")

    # 检查 image_providers.yaml
    image_config_path = Config.get_image_providers_path()
    if image_config_path.exists():
        image_config = Config.load_image_providers_config()
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
    else:
        logger.warning("⚠️  image_providers.yaml 不存在，将使用默认配置")

    logger.info("✅ 配置检查完成")


def _validate_network_exposure_config(host: str):
    """
    Refuse unauthenticated externally bound starts by default.

    REDINK_HOST may stay loopback behind nginx/Caddy while still being publicly
    exposed, so loopback binding is not treated as proof that auth is safe to
    omit. Set REDINK_ALLOW_UNAUTH_REMOTE=1 explicitly for isolated local/dev use.
    """
    if (os.environ.get("REDINK_AUTH_TOKEN") or "").strip():
        return

    if _env_flag("REDINK_ALLOW_UNAUTH_REMOTE"):
        return

    raise RuntimeError(
        "拒绝以未认证模式启动。请设置 REDINK_AUTH_TOKEN，"
        "或仅在明确受控环境中设置 REDINK_ALLOW_UNAUTH_REMOTE=1。"
    )


if __name__ == '__main__':
    app = create_app()
    app.run(
        host=Config.HOST,
        port=Config.PORT,
        debug=Config.DEBUG
    )
