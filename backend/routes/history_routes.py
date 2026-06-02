"""
历史记录相关 API 路由

包含功能：
- 创建/获取/更新/删除历史记录 (CRUD)
- 搜索历史记录
- 获取统计信息
- 扫描和同步任务图片
- 打包下载图片
"""

import os
import io
import zipfile
import logging
import re
from pathlib import Path
from typing import Optional, Any
from flask import Blueprint, request, jsonify, send_file
from backend.config import Config
from backend.services.history import get_history_service

logger = logging.getLogger(__name__)

ALLOWED_HISTORY_STATUSES = {"draft", "generating", "partial", "completed", "error"}


def create_history_blueprint():
    """创建历史记录路由蓝图（工厂函数，支持多次调用）"""
    history_bp = Blueprint('history', __name__)

    # ==================== CRUD 操作 ====================

    @history_bp.route('/history', methods=['POST'])
    def create_history():
        """
        创建历史记录（草稿）

        在用户生成大纲后立即调用，创建一个草稿状态的历史记录。
        初始状态为 draft，表示大纲已创建但尚未开始生成图片。

        请求体：
        - topic: 主题标题（必填）
        - outline: 大纲内容（必填），包含 pages 数组等
        - task_id: 关联的任务 ID（可选）

        返回：
        - success: 是否成功
        - record_id: 新创建的记录 ID（UUID 格式）

        状态流转：
            新建 -> draft（草稿状态）

        示例请求：
        {
            "topic": "小猫的冒险",
            "outline": {
                "title": "小猫的冒险",
                "pages": [
                    {"page": 1, "content": "..."},
                    {"page": 2, "content": "..."}
                ]
            },
            "task_id": "abc123"
        }
        """
        try:
            data = request.get_json(silent=True)
            if not isinstance(data, dict):
                return jsonify({"success": False, "error": "请求体必须是 JSON object"}), 400
            topic = data.get('topic')
            outline = data.get('outline')
            task_id = data.get('task_id')

            if not topic or not outline:
                return jsonify({
                    "success": False,
                    "error": "参数错误：topic 和 outline 不能为空。\n请提供主题和大纲内容。"
                }), 400

            if not isinstance(topic, str):
                return jsonify({"success": False, "error": "参数错误：topic 必须是字符串"}), 400
            if not isinstance(outline, dict):
                return jsonify({"success": False, "error": "参数错误：outline 必须是 JSON object"}), 400
            outline_error = _validate_outline_payload(outline)
            if outline_error:
                return jsonify({"success": False, "error": outline_error}), 400
            if task_id is not None and not isinstance(task_id, str):
                return jsonify({"success": False, "error": "参数错误：task_id 必须是字符串"}), 400

            history_service = get_history_service()
            record_id = history_service.create_record(topic, outline, task_id)

            return jsonify({
                "success": True,
                "record_id": record_id
            }), 200

        except Exception as e:
            error_msg = str(e)
            return jsonify({
                "success": False,
                "error": f"创建历史记录失败。\n错误详情: {error_msg}"
            }), 500

    @history_bp.route('/history', methods=['GET'])
    def list_history():
        """
        获取历史记录列表（分页）

        查询参数：
        - page: 页码（默认 1）
        - page_size: 每页数量（默认 20）
        - status: 状态过滤（可选：all/completed/draft）

        返回：
        - success: 是否成功
        - records: 记录列表
        - total: 总数
        - total_pages: 总页数
        """
        try:
            try:
                page = int(request.args.get('page', 1))
                page_size = int(request.args.get('page_size', 20))
            except Exception:
                return jsonify({"success": False, "error": "参数错误：page 和 page_size 必须是整数"}), 400
            if page < 1:
                return jsonify({"success": False, "error": "参数错误：page 必须大于等于 1"}), 400
            if page_size < 1 or page_size > 100:
                return jsonify({"success": False, "error": "参数错误：page_size 必须在 1 到 100 之间"}), 400
            status = request.args.get('status')
            if status and status not in {"all", *ALLOWED_HISTORY_STATUSES}:
                return jsonify({"success": False, "error": "参数错误：status 不合法"}), 400
            if status == "all":
                status = None

            history_service = get_history_service()
            result = history_service.list_records(page, page_size, status)

            return jsonify({
                "success": True,
                **result
            }), 200

        except Exception as e:
            error_msg = str(e)
            return jsonify({
                "success": False,
                "error": f"获取历史记录列表失败。\n错误详情: {error_msg}"
            }), 500

    @history_bp.route('/history/<record_id>', methods=['GET'])
    def get_history(record_id):
        """
        获取历史记录详情

        路径参数：
        - record_id: 记录 ID

        返回：
        - success: 是否成功
        - record: 完整的记录数据
        """
        try:
            history_service = get_history_service()
            record = history_service.get_record(record_id)

            if not record:
                return jsonify({
                    "success": False,
                    "error": f"历史记录不存在：{record_id}\n可能原因：记录已被删除或ID错误"
                }), 404

            return jsonify({
                "success": True,
                "record": record
            }), 200

        except Exception as e:
            error_msg = str(e)
            return jsonify({
                "success": False,
                "error": f"获取历史记录详情失败。\n错误详情: {error_msg}"
            }), 500

    @history_bp.route('/history/<record_id>/exists', methods=['GET'])
    def check_history_exists(record_id):
        """
        检查历史记录是否存在

        用于前端在开始生成前检查草稿记录是否已创建。

        路径参数：
        - record_id: 记录 ID

        返回：
        - exists: 记录是否存在（boolean）
        """
        try:
            history_service = get_history_service()
            exists = history_service.record_exists(record_id)

            return jsonify({
                "exists": exists
            }), 200

        except Exception as e:
            error_msg = str(e)
            return jsonify({
                "exists": False,
                "error": f"检查记录失败。\n错误详情: {error_msg}"
            }), 500

    @history_bp.route('/history/<record_id>', methods=['PUT'])
    def update_history(record_id):
        """
        更新历史记录

        支持部分更新，只更新提供的字段。
        每次更新都会自动刷新 updated_at 时间戳。

        路径参数：
        - record_id: 记录 ID

        请求体（均为可选）：
        - outline: 大纲内容（支持修改大纲）
        - images: 图片信息 { task_id, generated: [] }
        - status: 状态（draft/generating/partial/completed/error）
        - thumbnail: 缩略图文件名

        返回：
        - success: 是否成功

        状态流转说明：
            draft -> generating: 开始生成图片
            generating -> partial: 部分图片生成完成
            generating -> completed: 所有图片生成完成
            generating -> error: 生成过程出错
            partial -> generating: 继续生成剩余图片
            partial -> completed: 剩余图片生成完成

        示例请求（更新状态为生成中）：
        {
            "status": "generating"
        }

        示例请求（更新图片列表）：
        {
            "images": {
                "task_id": "abc123",
                "generated": ["0.png", "1.png"]
            },
            "status": "partial",
            "thumbnail": "0.png"
        }
        """
        try:
            data = request.get_json(silent=True)
            if not isinstance(data, dict):
                return jsonify({"success": False, "error": "请求体必须是 JSON object"}), 400
            outline = data.get('outline')
            images = data.get('images')
            content = data.get('content')
            status = data.get('status')
            thumbnail = data.get('thumbnail')

            validation_error = _validate_history_update_payload(
                outline=outline,
                images=images,
                content=content,
                status=status,
                thumbnail=thumbnail
            )
            if validation_error:
                return jsonify({"success": False, "error": validation_error}), 400

            history_service = get_history_service()
            success = history_service.update_record(
                record_id,
                outline=outline,
                images=images,
                content=content,
                status=status,
                thumbnail=thumbnail
            )

            if not success:
                return jsonify({
                    "success": False,
                    "error": f"更新历史记录失败：{record_id}\n可能原因：记录不存在或数据格式错误"
                }), 404

            return jsonify({
                "success": True
            }), 200

        except Exception as e:
            error_msg = str(e)
            return jsonify({
                "success": False,
                "error": f"更新历史记录失败。\n错误详情: {error_msg}"
            }), 500

    @history_bp.route('/history/<record_id>', methods=['DELETE'])
    def delete_history(record_id):
        """
        删除历史记录

        路径参数：
        - record_id: 记录 ID

        返回：
        - success: 是否成功
        """
        try:
            history_service = get_history_service()
            success = history_service.delete_record(record_id)

            if not success:
                return jsonify({
                    "success": False,
                    "error": f"删除历史记录失败：{record_id}\n可能原因：记录不存在或ID错误"
                }), 404

            return jsonify({
                "success": True
            }), 200

        except Exception as e:
            error_msg = str(e)
            return jsonify({
                "success": False,
                "error": f"删除历史记录失败。\n错误详情: {error_msg}"
            }), 500

    # ==================== 搜索和统计 ====================

    @history_bp.route('/history/search', methods=['GET'])
    def search_history():
        """
        搜索历史记录

        查询参数：
        - keyword: 搜索关键词（必填）

        返回：
        - success: 是否成功
        - records: 匹配的记录列表
        """
        try:
            keyword = request.args.get('keyword', '')

            if not keyword:
                return jsonify({
                    "success": False,
                    "error": "参数错误：keyword 不能为空。\n请提供搜索关键词。"
                }), 400

            history_service = get_history_service()
            results = history_service.search_records(keyword)

            return jsonify({
                "success": True,
                "records": results
            }), 200

        except Exception as e:
            error_msg = str(e)
            return jsonify({
                "success": False,
                "error": f"搜索历史记录失败。\n错误详情: {error_msg}"
            }), 500

    @history_bp.route('/history/stats', methods=['GET'])
    def get_history_stats():
        """
        获取历史记录统计信息

        返回：
        - success: 是否成功
        - total: 总记录数
        - by_status: 按状态分组的统计
        """
        try:
            history_service = get_history_service()
            stats = history_service.get_statistics()

            return jsonify({
                "success": True,
                **stats
            }), 200

        except Exception as e:
            error_msg = str(e)
            return jsonify({
                "success": False,
                "error": f"获取历史记录统计失败。\n错误详情: {error_msg}"
            }), 500

    # ==================== 扫描和同步 ====================

    @history_bp.route('/history/scan/<task_id>', methods=['GET'])
    def scan_task(task_id):
        """
        扫描单个任务并同步图片列表

        路径参数：
        - task_id: 任务 ID

        返回：
        - success: 是否成功
        - images: 同步后的图片列表
        """
        try:
            history_service = get_history_service()
            result = history_service.scan_and_sync_task_images(task_id)

            if not result.get("success"):
                err = str(result.get("error") or "")
                if "路径不安全" in err:
                    return jsonify(result), 400
                return jsonify(result), 404

            return jsonify(result), 200

        except Exception as e:
            error_msg = str(e)
            return jsonify({
                "success": False,
                "error": f"扫描任务失败。\n错误详情: {error_msg}"
            }), 500

    @history_bp.route('/history/scan-all', methods=['POST'])
    def scan_all_tasks():
        """
        扫描所有任务并同步图片列表

        返回：
        - success: 是否成功
        - total_tasks: 扫描的任务总数
        - synced: 成功同步的任务数
        - failed: 失败的任务数
        - orphan_tasks: 孤立任务列表（有图片但无记录）
        """
        try:
            history_service = get_history_service()
            result = history_service.scan_all_tasks()

            if not result.get("success"):
                return jsonify(result), 500

            return jsonify(result), 200

        except Exception as e:
            error_msg = str(e)
            return jsonify({
                "success": False,
                "error": f"扫描所有任务失败。\n错误详情: {error_msg}"
            }), 500

    # ==================== 下载功能 ====================

    @history_bp.route('/history/<record_id>/download', methods=['GET'])
    def download_history_zip(record_id):
        """
        下载历史记录的所有图片为 ZIP 文件

        路径参数：
        - record_id: 记录 ID

        返回：
        - 成功：ZIP 文件下载
        - 失败：JSON 错误信息
        """
        try:
            history_service = get_history_service()
            record = history_service.get_record(record_id)

            if not record:
                return jsonify({
                    "success": False,
                    "error": f"历史记录不存在：{record_id}"
                }), 404

            task_id = record.get('images', {}).get('task_id')
            if not task_id:
                return jsonify({
                    "success": False,
                    "error": "该记录没有关联的任务图片"
                }), 404

            # 获取任务目录（防止路径遍历/符号链接）
            task_dir = _safe_task_dir(history_service.history_dir, task_id)
            if not task_dir:
                return jsonify({
                    "success": False,
                    "error": f"任务目录不存在或路径不安全：{task_id}"
                }), 404

            source_bytes = _safe_image_source_bytes(task_dir)
            if source_bytes > Config.MAX_HISTORY_ZIP_SOURCE_BYTES:
                return jsonify({
                    "success": False,
                    "error": (
                        "历史图片总大小超过下载限制。"
                        f"当前 {source_bytes} bytes，限制 {Config.MAX_HISTORY_ZIP_SOURCE_BYTES} bytes。"
                    )
                }), 413

            # 创建内存中的 ZIP 文件
            zip_buffer = _create_images_zip(task_dir, record)

            # 生成安全的下载文件名
            title = record.get('title', 'images')
            safe_title = _sanitize_filename(title)
            filename = f"{safe_title}.zip"

            return send_file(
                zip_buffer,
                mimetype='application/zip',
                as_attachment=True,
                download_name=filename
            )

        except Exception as e:
            error_msg = str(e)
            return jsonify({
                "success": False,
                "error": f"下载失败。\n错误详情: {error_msg}"
            }), 500

    return history_bp


def _is_safe_task_id(task_id: str) -> bool:
    return re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", task_id or "") is not None


def _is_safe_image_filename(filename: str) -> bool:
    return re.fullmatch(r"(thumb_)?\d+\.(png|jpg|jpeg)", filename or "", flags=re.IGNORECASE) is not None


def _validate_generated_list(value: Any) -> bool:
    if not isinstance(value, list):
        return False
    for item in value:
        if item is None:
            continue
        if not isinstance(item, str) or not _is_safe_image_filename(item):
            return False
    return True


def _validate_history_update_payload(
    *,
    outline: Any,
    images: Any,
    content: Any,
    status: Any,
    thumbnail: Any
) -> Optional[str]:
    if outline is not None and not isinstance(outline, dict):
        return "参数错误：outline 必须是 JSON object"
    if outline is not None:
        outline_error = _validate_outline_payload(outline)
        if outline_error:
            return outline_error

    if images is not None:
        if not isinstance(images, dict):
            return "参数错误：images 必须是 JSON object"
        task_id = images.get("task_id")
        if task_id is not None:
            if not isinstance(task_id, str) or not _is_safe_task_id(task_id):
                return "参数错误：images.task_id 不安全"
        if "generated" in images and not _validate_generated_list(images.get("generated")):
            return "参数错误：images.generated 必须是安全文件名数组"

    if content is not None:
        if not isinstance(content, dict):
            return "参数错误：content 必须是 JSON object"
        titles = content.get("titles", [])
        tags = content.get("tags", [])
        copywriting = content.get("copywriting", "")
        if not isinstance(titles, list) or not all(isinstance(x, str) for x in titles):
            return "参数错误：content.titles 必须是字符串数组"
        if not isinstance(tags, list) or not all(isinstance(x, str) for x in tags):
            return "参数错误：content.tags 必须是字符串数组"
        if not isinstance(copywriting, str):
            return "参数错误：content.copywriting 必须是字符串"

    if status is not None:
        if not isinstance(status, str) or status not in ALLOWED_HISTORY_STATUSES:
            return "参数错误：status 不合法"

    if thumbnail is not None:
        if not isinstance(thumbnail, str) or not _is_safe_image_filename(thumbnail):
            return "参数错误：thumbnail 必须是安全图片文件名"

    return None


def _validate_outline_payload(outline: Any) -> Optional[str]:
    if not isinstance(outline, dict):
        return "参数错误：outline 必须是 JSON object"

    pages = outline.get("pages")
    if not isinstance(pages, list) or not pages:
        return "参数错误：outline.pages 不能为空且必须是数组"

    seen_indices = set()
    for page in pages:
        if not isinstance(page, dict):
            return "参数错误：outline.pages 中的每一项都必须是 JSON object"
        index = page.get("index")
        if not isinstance(index, int) or index < 0:
            return "参数错误：outline.pages 中的 index 必须是非负整数"
        if "content" not in page or not isinstance(page.get("content"), str):
            return "参数错误：outline.pages 中的 content 必须是字符串"
        page_type = page.get("type")
        if page_type is not None and (not isinstance(page_type, str) or not page_type):
            return "参数错误：outline.pages 中的 type 必须是字符串"
        if index in seen_indices:
            return "参数错误：outline.pages 中的 index 不能重复"
        seen_indices.add(index)

    if seen_indices != set(range(len(pages))):
        return "参数错误：outline.pages 中的 index 必须从 0 开始连续"

    return None


def _create_images_zip(task_dir: str, record: Optional[dict] = None) -> io.BytesIO:
    """
    创建包含所有图片的 ZIP 文件

    Args:
        task_dir: 任务目录路径

    Returns:
        io.BytesIO: 内存中的 ZIP 文件
    """
    memory_file = io.BytesIO()

    task_path = Path(task_dir).resolve()
    if Path(task_dir).is_symlink():
        raise ValueError("任务目录为符号链接，已拒绝打包")

    with zipfile.ZipFile(memory_file, 'w', zipfile.ZIP_DEFLATED) as zf:
        # 附带元信息
        if record:
            try:
                title = record.get("title", "")
                record_id = record.get("id", "")
                created_at = record.get("created_at", "")
                updated_at = record.get("updated_at", "")
                status = record.get("status", "")
                task_id = (record.get("images") or {}).get("task_id", "")
                pages = (record.get("outline") or {}).get("pages") or []
                page_count = len(pages)
                style_hint = record.get("style_hint", "")

                meta_lines = [
                    f"Title: {title}",
                    f"Record ID: {record_id}",
                    f"Status: {status}",
                    f"Created At: {created_at}",
                    f"Updated At: {updated_at}",
                    f"Task ID: {task_id}",
                    f"Pages: {page_count}",
                ]
                if style_hint:
                    meta_lines.append(f"Style Hint: {style_hint}")
                zf.writestr("meta.txt", "\n".join(meta_lines) + "\n")

                outline_raw = (record.get("outline") or {}).get("raw", "")
                if outline_raw:
                    zf.writestr("outline.txt", str(outline_raw))

                content = record.get("content") or {}
                titles = content.get("titles") or []
                copywriting = content.get("copywriting") or ""
                tags = content.get("tags") or []
                if titles or copywriting or tags:
                    parts = []
                    if titles:
                        parts.append("Titles:")
                        parts.extend([f"- {t}" for t in titles])
                        parts.append("")
                    if copywriting:
                        parts.append("Copywriting:")
                        parts.append(str(copywriting))
                        parts.append("")
                    if tags:
                        parts.append("Tags:")
                        parts.append(" ".join([f"#{t}" for t in tags]))
                        parts.append("")
                    zf.writestr("content.txt", "\n".join(parts).strip() + "\n")
            except Exception:
                # 元信息写入失败不影响图片打包
                pass

        # 遍历任务目录中的所有图片（排除缩略图）
        for filename in os.listdir(task_dir):
            # 跳过缩略图文件
            if filename.startswith('thumb_'):
                continue

            if filename.endswith(('.png', '.jpg', '.jpeg')):
                file_path = (task_path / filename)

                # 跳过符号链接
                try:
                    if file_path.is_symlink():
                        continue
                except Exception:
                    continue

                # 确保在 task_dir 内
                try:
                    file_path.resolve().relative_to(task_path)
                except Exception:
                    continue

                if not file_path.exists() or not file_path.is_file():
                    continue

                # 生成归档文件名（page_N.png 格式）
                try:
                    index = int(filename.split('.')[0])
                    archive_name = f"page_{index + 1}.png"
                except ValueError:
                    archive_name = filename

                zf.write(str(file_path), archive_name)

    # 将指针移到开始位置
    memory_file.seek(0)
    return memory_file


def _safe_image_source_bytes(task_dir: str) -> int:
    task_path = Path(task_dir).resolve()
    if Path(task_dir).is_symlink():
        raise ValueError("任务目录为符号链接，已拒绝统计")

    total = 0
    for filename in os.listdir(task_dir):
        if filename.startswith('thumb_') or not filename.endswith(('.png', '.jpg', '.jpeg')):
            continue

        file_path = task_path / filename
        try:
            if file_path.is_symlink():
                continue
            file_path.resolve().relative_to(task_path)
        except Exception:
            continue

        if file_path.exists() and file_path.is_file():
            total += file_path.stat().st_size

    return total


def _sanitize_filename(title: str) -> str:
    """
    清理文件名中的非法字符

    Args:
        title: 原始标题

    Returns:
        str: 安全的文件名
    """
    # 只保留字母、数字、空格、连字符和下划线
    safe_title = "".join(
        c for c in (title or "")
        if c.isalnum() or c in (' ', '-', '_') or ('\u4e00' <= c <= '\u9fff')
    ).strip()

    if not safe_title:
        return 'images'
    return _truncate_utf8_filename_stem(safe_title, max_bytes=80) or 'images'


def _truncate_utf8_filename_stem(value: str, *, max_bytes: int) -> str:
    result = []
    used = 0
    for char in value:
        char_bytes = len(char.encode("utf-8"))
        if used + char_bytes > max_bytes:
            break
        result.append(char)
        used += char_bytes
    return "".join(result).rstrip()


def _safe_task_dir(history_root: str, task_id: str) -> Optional[str]:
    """
    防止路径遍历/符号链接：
    - task_id 只能是安全字符
    - resolve 后必须在 history_root 内
    - 目录不能是 symlink
    """
    import re

    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", task_id or ""):
        return None

    base = Path(history_root).resolve()
    target = (base / task_id).resolve()
    try:
        target.relative_to(base)
    except Exception:
        return None

    try:
        if (base / task_id).is_symlink():
            return None
    except Exception:
        return None

    if not target.exists() or not target.is_dir():
        return None

    return str(target)
