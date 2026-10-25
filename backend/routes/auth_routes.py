from flask import Blueprint, request, jsonify, make_response
from backend.app import IMAGE_AUTH_COOKIE
from urllib.parse import quote

def create_auth_blueprint():
    auth_bp = Blueprint('auth', __name__)

    @auth_bp.route('/auth/session', methods=['POST'])
    def login():
        data = request.get_json(silent=True) or {}
        token = data.get('token', '').strip()
        if not token:
            return jsonify({"success": False, "error": "Missing token"}), 400

        resp = make_response(jsonify({"success": True}))
        # Use HttpOnly cookie
        # Also need to make sure we support both HTTP and HTTPS safely, but HttpOnly is key.
        secure = request.is_secure or request.headers.get("X-Forwarded-Proto") == "https"
        resp.set_cookie(
            IMAGE_AUTH_COOKIE,
            quote(token),
            httponly=True,
            secure=secure,
            samesite='Lax',
            max_age=2592000,
            path='/'
        )
        return resp

    @auth_bp.route('/auth/session', methods=['DELETE'])
    def logout():
        resp = make_response(jsonify({"success": True}))
        resp.set_cookie(
            IMAGE_AUTH_COOKIE,
            '',
            httponly=True,
            samesite='Lax',
            max_age=0,
            path='/'
        )
        return resp

    return auth_bp
