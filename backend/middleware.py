"""Authentication and rate limiting middleware"""
import logging
import os
from functools import wraps
from flask import request, jsonify

logger = logging.getLogger(__name__)


def _get_auth_token():
    """Read auth token from environment at call time (not import time)."""
    return os.environ.get('REDINK_AUTH_TOKEN', '')


def require_auth(f):
    """
    Authentication decorator.

    When REDINK_AUTH_TOKEN is set, requires Bearer token in Authorization header.
    When REDINK_AUTH_TOKEN is not set, authentication is disabled (open access).
    """
    @wraps(f)
    def decorated(*args, **kwargs):
        auth_token = _get_auth_token()
        if not auth_token:
            return f(*args, **kwargs)

        auth_header = request.headers.get('Authorization', '')
        if not auth_header.startswith('Bearer '):
            return jsonify({
                'success': False,
                'error': '未提供认证令牌。请在请求头中添加 Authorization: Bearer <token>'
            }), 401

        token = auth_header[7:]
        if token != auth_token:
            logger.warning(f"认证失败: 来自 {request.remote_addr}")
            return jsonify({
                'success': False,
                'error': '认证令牌无效'
            }), 401

        return f(*args, **kwargs)
    return decorated
