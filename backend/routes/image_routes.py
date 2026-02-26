"""
图片生成相关 API 路由

包含功能：
- 批量生成图片（SSE 流式返回）
- 获取图片
- 重试/重新生成单张图片
- 批量重试失败图片
- 获取任务状态
"""

import os
import json
import base64
import logging
import re
from pathlib import Path
from flask import Blueprint, request, jsonify, Response, send_file
from backend.config import Config
from backend.services.image import get_image_service
from .utils import log_request, log_error

logger = logging.getLogger(__name__)


def create_image_blueprint():
    """创建图片路由蓝图（工厂函数，支持多次调用）"""
    image_bp = Blueprint('image', __name__)

    def _is_safe_task_id(task_id: str) -> bool:
        return re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", str(task_id) or "") is not None

    def _safe_image_path(history_root: Path, task_id: str, filename: str) -> Path | None:
        """
        防止路径遍历：确保最终路径在 history_root 内，且只允许预期文件名。

        仅允许：{index}.png 或 thumb_{index}.png
        """
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", task_id or ""):
            return None

        # NOTE: use single backslashes in raw regex. `\\d` would match the literal string "\d".
        if not re.fullmatch(r"(thumb_)?\d+\.png", filename or ""):
            return None

        base = history_root.resolve()
        target = (base / task_id / filename).resolve()
        try:
            target.relative_to(base)
        except Exception:
            return None

        # Never serve symlinks
        try:
            if target.is_symlink():
                return None
        except Exception:
            return None

        if not target.exists() or not target.is_file():
            return None

        return target

    # ==================== 图片生成 ====================

    @image_bp.route('/generate', methods=['POST'])
    def generate_images():
        """
        批量生成图片（SSE 流式返回）

        请求体：
        - pages: 页面列表（必填）
        - task_id: 任务 ID
        - full_outline: 完整大纲文本
        - user_topic: 用户原始输入主题
        - user_images: base64 编码的用户参考图片列表

        返回：
        SSE 事件流，包含以下事件类型：
        - image: 单张图片生成完成
        - error: 生成错误
        - complete: 全部完成
        """
        try:
            data = request.get_json(silent=True)
            if not isinstance(data, dict):
                return jsonify({"success": False, "error": "请求体必须是 JSON object"}), 400
            pages = data.get('pages')
            task_id = data.get('task_id')
            full_outline = data.get('full_outline', '')
            user_topic = data.get('user_topic', '')
            style_hint = data.get('style_hint', '')

            if task_id is not None and task_id != "" and not _is_safe_task_id(task_id):
                return jsonify({"success": False, "error": "参数错误：task_id 不安全"}), 400

            # 解析 base64 格式的用户参考图片
            user_images = _parse_base64_images(data.get('user_images', []))

            log_request('/generate', {
                'pages_count': len(pages) if pages else 0,
                'task_id': task_id,
                'user_topic': user_topic[:50] if user_topic else None,
                'user_images': user_images
            })

            if not pages or not isinstance(pages, list):
                logger.warning("图片生成请求缺少 pages 参数")
                return jsonify({
                    "success": False,
                    "error": "参数错误：pages 不能为空。\n请提供要生成的页面列表数据。"
                }), 400

            logger.info(f"🖼️  开始图片生成任务: {task_id}, 共 {len(pages)} 页")
            image_service = get_image_service()

            def generate():
                """SSE 事件生成器"""
                for event in image_service.generate_images(
                    pages, task_id, full_outline,
                    user_images=user_images if user_images else None,
                    user_topic=user_topic,
                    style_hint=style_hint
                ):
                    event_type = event["event"]
                    event_data = event["data"]

                    # 格式化为 SSE 格式
                    yield f"event: {event_type}\n"
                    yield f"data: {json.dumps(event_data, ensure_ascii=False)}\n\n"

            return Response(
                generate(),
                mimetype='text/event-stream',
                headers={
                    'Cache-Control': 'no-cache',
                    'X-Accel-Buffering': 'no',
                }
            )

        except ValueError as e:
            return jsonify({
                "success": False,
                "error": str(e)
            }), 400
        except Exception as e:
            log_error('/generate', e)
            error_msg = str(e)
            return jsonify({
                "success": False,
                "error": f"图片生成异常。\n错误详情: {error_msg}\n建议：检查图片生成服务配置和后端日志"
            }), 500

    # ==================== 图片获取 ====================

    @image_bp.route('/images/<task_id>/<filename>', methods=['GET'])
    def get_image(task_id, filename):
        """
        获取图片文件

        路径参数：
        - task_id: 任务 ID
        - filename: 文件名

        查询参数：
        - thumbnail: 是否返回缩略图（默认 true）

        返回：
        - 成功：图片文件
        - 失败：JSON 错误信息
        """
        try:
            logger.debug(f"获取图片: {task_id}/{filename}")

            # 检查是否请求缩略图
            thumbnail = request.args.get('thumbnail', 'true').lower() == 'true'

            history_root = Path(__file__).parent.parent.parent / "history"

            if thumbnail:
                thumb_filename = f"thumb_{filename}"
                safe_thumb = _safe_image_path(history_root, task_id, thumb_filename)
                if safe_thumb:
                    return send_file(str(safe_thumb), mimetype='image/png')

            safe_file = _safe_image_path(history_root, task_id, filename)
            if not safe_file:
                return jsonify({
                    "success": False,
                    "error": f"图片不存在或路径不安全：{task_id}/{filename}"
                }), 404

            return send_file(str(safe_file), mimetype='image/png')

        except Exception as e:
            log_error('/images', e)
            error_msg = str(e)
            return jsonify({
                "success": False,
                "error": f"获取图片失败: {error_msg}"
            }), 500

    # ==================== 重试和重新生成 ====================

    @image_bp.route('/retry', methods=['POST'])
    def retry_single_image():
        """
        重试生成单张失败的图片

        请求体：
        - task_id: 任务 ID（必填）
        - page: 页面信息（必填）
        - use_reference: 是否使用参考图（默认 true）

        返回：
        - success: 是否成功
        - image_url: 新图片 URL
        """
        try:
            data = request.get_json(silent=True)
            if not isinstance(data, dict):
                return jsonify({"success": False, "error": "请求体必须是 JSON object"}), 400
            task_id = data.get('task_id')
            page = data.get('page')
            use_reference = data.get('use_reference', True)
            style_hint = data.get('style_hint', '')

            log_request('/retry', {
                'task_id': task_id,
                'page_index': page.get('index') if isinstance(page, dict) else None
            })

            if not task_id or not isinstance(page, dict):
                logger.warning("重试请求缺少必要参数")
                return jsonify({
                    "success": False,
                    "error": "参数错误：task_id 和 page 不能为空。\n请提供任务ID和页面信息。"
                }), 400

            if not _is_safe_task_id(task_id):
                return jsonify({"success": False, "error": "参数错误：task_id 不安全"}), 400

            logger.info(f"🔄 重试生成图片: task={task_id}, page={page.get('index')}")
            image_service = get_image_service()
            result = image_service.retry_single_image(task_id, page, use_reference, style_hint=style_hint)

            if result["success"]:
                logger.info(f"✅ 图片重试成功: {result.get('image_url')}")
            else:
                logger.error(f"❌ 图片重试失败: {result.get('error')}")

            return jsonify(result), 200 if result["success"] else 500

        except Exception as e:
            log_error('/retry', e)
            error_msg = str(e)
            return jsonify({
                "success": False,
                "error": f"重试图片生成失败。\n错误详情: {error_msg}"
            }), 500

    @image_bp.route('/retry-failed', methods=['POST'])
    def retry_failed_images():
        """
        批量重试失败的图片（SSE 流式返回）

        请求体：
        - task_id: 任务 ID（必填）
        - pages: 要重试的页面列表（必填）

        返回：
        SSE 事件流
        """
        try:
            data = request.get_json(silent=True)
            if not isinstance(data, dict):
                return jsonify({"success": False, "error": "请求体必须是 JSON object"}), 400
            task_id = data.get('task_id')
            pages = data.get('pages')

            log_request('/retry-failed', {
                'task_id': task_id,
                'pages_count': len(pages) if pages else 0
            })

            if not task_id or not pages or not isinstance(pages, list):
                logger.warning("批量重试请求缺少必要参数")
                return jsonify({
                    "success": False,
                    "error": "参数错误：task_id 和 pages 不能为空。\n请提供任务ID和要重试的页面列表。"
                }), 400

            if not _is_safe_task_id(task_id):
                return jsonify({"success": False, "error": "参数错误：task_id 不安全"}), 400

            logger.info(f"🔄 批量重试失败图片: task={task_id}, 共 {len(pages)} 页")
            image_service = get_image_service()

            def generate():
                """SSE 事件生成器"""
                for event in image_service.retry_failed_images(task_id, pages):
                    event_type = event["event"]
                    event_data = event["data"]

                    yield f"event: {event_type}\n"
                    yield f"data: {json.dumps(event_data, ensure_ascii=False)}\n\n"

            return Response(
                generate(),
                mimetype='text/event-stream',
                headers={
                    'Cache-Control': 'no-cache',
                    'X-Accel-Buffering': 'no',
                }
            )

        except Exception as e:
            log_error('/retry-failed', e)
            error_msg = str(e)
            return jsonify({
                "success": False,
                "error": f"批量重试失败。\n错误详情: {error_msg}"
            }), 500

    @image_bp.route('/regenerate', methods=['POST'])
    def regenerate_image():
        """
        重新生成图片（即使成功的也可以重新生成）

        请求体：
        - task_id: 任务 ID（必填）
        - page: 页面信息（必填）
        - use_reference: 是否使用参考图（默认 true）
        - full_outline: 完整大纲文本（用于上下文）
        - user_topic: 用户原始输入主题

        返回：
        - success: 是否成功
        - image_url: 新图片 URL
        """
        try:
            data = request.get_json(silent=True)
            if not isinstance(data, dict):
                return jsonify({"success": False, "error": "请求体必须是 JSON object"}), 400
            task_id = data.get('task_id')
            page = data.get('page')
            use_reference = data.get('use_reference', True)
            full_outline = data.get('full_outline', '')
            user_topic = data.get('user_topic', '')
            style_hint = data.get('style_hint', '')

            log_request('/regenerate', {
                'task_id': task_id,
                'page_index': page.get('index') if isinstance(page, dict) else None
            })

            if not task_id or not isinstance(page, dict):
                logger.warning("重新生成请求缺少必要参数")
                return jsonify({
                    "success": False,
                    "error": "参数错误：task_id 和 page 不能为空。\n请提供任务ID和页面信息。"
                }), 400

            if not _is_safe_task_id(task_id):
                return jsonify({"success": False, "error": "参数错误：task_id 不安全"}), 400

            logger.info(f"🔄 重新生成图片: task={task_id}, page={page.get('index')}")
            image_service = get_image_service()
            result = image_service.regenerate_image(
                task_id, page, use_reference,
                full_outline=full_outline,
                user_topic=user_topic,
                style_hint=style_hint
            )

            if result["success"]:
                logger.info(f"✅ 图片重新生成成功: {result.get('image_url')}")
            else:
                logger.error(f"❌ 图片重新生成失败: {result.get('error')}")

            return jsonify(result), 200 if result["success"] else 500

        except Exception as e:
            log_error('/regenerate', e)
            error_msg = str(e)
            return jsonify({
                "success": False,
                "error": f"重新生成图片失败。\n错误详情: {error_msg}"
            }), 500

    # ==================== 任务状态 ====================

    @image_bp.route('/task/<task_id>/cancel', methods=['POST'])
    def cancel_task(task_id):
        """取消正在进行的生成任务（尽量停止后续页面生成）"""
        try:
            image_service = get_image_service()
            ok = image_service.cancel_task(task_id)
            if not ok:
                return jsonify({
                    "success": False,
                    "error": f"任务不存在：{task_id}"
                }), 404

            return jsonify({
                "success": True,
                "task_id": task_id
            }), 200
        except Exception as e:
            error_msg = str(e)
            return jsonify({
                "success": False,
                "error": f"取消任务失败。\n错误详情: {error_msg}"
            }), 500

    @image_bp.route('/task/<task_id>', methods=['GET'])
    def get_task_state(task_id):
        """
        获取任务状态

        路径参数：
        - task_id: 任务 ID

        返回：
        - success: 是否成功
        - state: 任务状态
          - generated: 已生成的图片
          - failed: 失败的图片
          - has_cover: 是否有封面图
        """
        try:
            image_service = get_image_service()
            state = image_service.get_task_state(task_id)

            if state is None:
                return jsonify({
                    "success": False,
                    "error": f"任务不存在：{task_id}\n可能原因：\n1. 任务ID错误\n2. 任务已过期或被清理\n3. 服务重启导致状态丢失"
                }), 404

            # 不返回封面图片数据（太大）
            safe_state = {
                "generated": state.get("generated", {}),
                "failed": state.get("failed", {}),
                "has_cover": state.get("cover_image") is not None
            }

            return jsonify({
                "success": True,
                "state": safe_state
            }), 200

        except Exception as e:
            error_msg = str(e)
            return jsonify({
                "success": False,
                "error": f"获取任务状态失败。\n错误详情: {error_msg}"
            }), 500

    # ==================== 健康检查 ====================

    @image_bp.route('/health', methods=['GET'])
    def health_check():
        """
        健康检查接口

        返回：
        - success: 服务是否正常
        - message: 状态消息
        """
        return jsonify({
            "success": True,
            "message": "服务正常运行"
        }), 200

    return image_bp


# ==================== 辅助函数 ====================

def _parse_base64_images(images_base64: list) -> list:
    """
    解析 base64 编码的图片列表

    Args:
        images_base64: base64 编码的图片字符串列表

    Returns:
        list: 解码后的图片二进制数据列表
    """
    if not images_base64:
        return []

    if not isinstance(images_base64, list):
        raise ValueError("参数错误：user_images 必须是数组")

    if len(images_base64) > Config.MAX_BASE64_IMAGES:
        raise ValueError(f"参数错误：user_images 最多允许 {Config.MAX_BASE64_IMAGES} 张图片")

    images = []
    total_bytes = 0
    for img_b64 in images_base64:
        if not isinstance(img_b64, str) or not img_b64:
            raise ValueError("参数错误：user_images 中存在无效的 base64 字符串")

        # 移除可能的 data URL 前缀（如 data:image/png;base64,）
        if ',' in img_b64:
            img_b64 = img_b64.split(',', 1)[1]

        img_b64 = img_b64.strip()

        # Rough pre-check to avoid decoding extremely large payloads.
        max_b64_len = int(Config.MAX_BASE64_IMAGE_BYTES * 4 / 3) + 8
        if len(img_b64) > max_b64_len:
            raise ValueError("参数错误：user_images 中存在过大的图片数据")

        try:
            img = base64.b64decode(img_b64, validate=True)
        except Exception as e:
            raise ValueError("参数错误：user_images 中存在无效的 base64 数据") from e

        if len(img) > Config.MAX_BASE64_IMAGE_BYTES:
            raise ValueError("参数错误：user_images 中存在过大的图片数据")

        total_bytes += len(img)
        if total_bytes > Config.MAX_BASE64_TOTAL_BYTES:
            raise ValueError("参数错误：user_images 总大小超过限制")

        images.append(img)

    return images
