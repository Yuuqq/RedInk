"""Authentication and rate limiting middleware"""
import logging
import hmac
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
    Without REDINK_AUTH_TOKEN, app-level startup/request guards reject access
    unless REDINK_ALLOW_UNAUTH_REMOTE=1 explicitly opts into unauthenticated mode.
    """
    @wraps(f)
    def decorated(*args, **kwargs):
        auth_token = _get_auth_token()
        if not auth_token:
            return f(*args, **kwargs)

        # We allow both header and cookie authentication now
        from backend.app import _request_has_valid_auth
        if not _request_has_valid_auth(auth_token):
            logger.warning(f"认证失败: 来自 {request.remote_addr}")
            return jsonify({
                'success': False,
                'error': '认证令牌无效或缺失。'
            }), 401

        return f(*args, **kwargs)
    return decorated
