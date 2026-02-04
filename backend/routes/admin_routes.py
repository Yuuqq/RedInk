"""
Admin / Management API

These endpoints are intended for local management / monitoring, e.g.:
- health & upstream connectivity checks
- list active tasks in memory
- cleanup in-memory task state and/or task files

By default, access is limited to localhost. Set REDINK_ADMIN_ALLOW_REMOTE=1
to allow non-local access.
"""

import os
import time
import platform
import logging
import shutil
import ipaddress
import re
from pathlib import Path
from typing import Dict, Any

import yaml
import requests
from flask import Blueprint, jsonify, request, send_file

from backend.services.image import get_image_service

logger = logging.getLogger(__name__)


def _is_local_request() -> bool:
    allow_remote = os.environ.get("REDINK_ADMIN_ALLOW_REMOTE", "").strip().lower() in ("1", "true", "yes")
    if allow_remote:
        return True

    trust_private = os.environ.get("REDINK_ADMIN_TRUST_PRIVATE", "").strip().lower() in ("1", "true", "yes")
    trust_xff = os.environ.get("REDINK_ADMIN_TRUST_XFF", "").strip().lower() in ("1", "true", "yes")

    # X-Forwarded-For is easy to spoof unless you fully control the proxy.
    # Default: do not trust it.
    remote_addr = request.remote_addr or ""
    if trust_xff:
        xff = request.headers.get("X-Forwarded-For")
        if xff:
            # Prefer the last hop IP (closest proxy) when trusting XFF.
            remote_addr = xff.split(",")[-1].strip() or remote_addr
    try:
        ip = ipaddress.ip_address(remote_addr)
        if ip.is_loopback:
            return True
        if trust_private and ip.is_private:
            return True
        return False
    except Exception:
        return False


def _require_local():
    if not _is_local_request():
        return jsonify({
            "success": False,
            "error": (
                "该管理接口默认仅允许本机访问（loopback）。\n"
                "如需允许内网访问：REDINK_ADMIN_TRUST_PRIVATE=1\n"
                "如需信任 X-Forwarded-For：REDINK_ADMIN_TRUST_XFF=1（仅在你完全控制反代时）\n"
                "如需允许任意远程访问（不推荐）：REDINK_ADMIN_ALLOW_REMOTE=1"
            )
        }), 403
    return None


def _read_yaml(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _get_project_root() -> Path:
    return Path(__file__).parent.parent.parent


def _get_log_file() -> Path:
    root = _get_project_root()
    log_dir = root / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    env_path = os.environ.get("REDINK_LOG_FILE")
    if env_path:
        candidate = Path(env_path)
        # Default: only allow logs inside ./logs to avoid arbitrary file download.
        allow_any = os.environ.get("REDINK_ADMIN_ALLOW_LOG_ANY_PATH", "").strip().lower() in ("1", "true", "yes")
        if allow_any:
            return candidate
        try:
            candidate.resolve().relative_to(log_dir.resolve())
            return candidate
        except Exception:
            logger.warning(f"REDINK_LOG_FILE 不在 logs/ 目录内，已忽略: {env_path}")

    return log_dir / "redink.log"


def _read_log_chunk(path: Path, offset: int, max_bytes: int) -> Dict[str, Any]:
    if offset < 0:
        offset = 0
    if max_bytes <= 0:
        max_bytes = 64 * 1024
    max_bytes = min(max_bytes, 2 * 1024 * 1024)  # hard cap 2MB

    if not path.exists():
        return {"offset": 0, "next_offset": 0, "content": "", "exists": False, "size": 0}

    with open(path, "rb") as f:
        f.seek(0, os.SEEK_END)
        size = f.tell()
        if offset > size:
            offset = max(0, size - max_bytes)

        f.seek(offset)
        data = f.read(max_bytes)
        next_offset = offset + len(data)

    text = data.decode("utf-8", errors="replace")
    return {"offset": offset, "next_offset": next_offset, "content": text, "exists": True, "size": size}


def _dir_size_bytes(path: Path) -> int:
    total = 0
    try:
        for p in path.rglob("*"):
            if p.is_file():
                try:
                    total += p.stat().st_size
                except Exception:
                    pass
    except Exception:
        return 0
    return total


def _history_stats() -> Dict[str, Any]:
    root = _get_project_root()
    history_root = root / "history"
    history_root.mkdir(parents=True, exist_ok=True)
    index_path = history_root / "index.json"

    records = []
    if index_path.exists():
        try:
            import json
            records = (json.loads(index_path.read_text(encoding="utf-8")) or {}).get("records", [])
        except Exception:
            records = []

    referenced_task_ids = set()
    for r in records:
        tid = (r or {}).get("task_id")
        if tid:
            referenced_task_ids.add(str(tid))

    task_dirs = []
    total_bytes = 0
    for p in history_root.iterdir():
        if p.is_dir():
            sz = _dir_size_bytes(p)
            total_bytes += sz
            try:
                mtime = p.stat().st_mtime
            except Exception:
                mtime = None
            task_dirs.append({"task_id": p.name, "bytes": sz, "mtime": mtime})

    task_dirs.sort(key=lambda x: x["bytes"], reverse=True)
    newest_dirs = sorted(task_dirs, key=lambda x: (x["mtime"] or 0), reverse=True)
    orphan_dirs = [d["task_id"] for d in task_dirs if d["task_id"] not in referenced_task_ids]
    referenced_missing = [tid for tid in referenced_task_ids if not (history_root / tid).exists()]

    return {
        "history_root": str(history_root),
        "total_task_dirs": len(task_dirs),
        "total_records": len(records),
        "total_bytes": total_bytes,
        "orphan_task_dirs": orphan_dirs[:200],
        "orphan_task_dirs_count": len(orphan_dirs),
        "referenced_missing_task_dirs": referenced_missing[:200],
        "referenced_missing_task_dirs_count": len(referenced_missing),
        "largest_task_dirs": task_dirs[:20],
        "newest_task_dirs": newest_dirs[:20],
    }


def _safe_task_id(task_id: str) -> bool:
    # Prevent path traversal and weird names; keep it strict and predictable.
    # Matches task_xxx, UUID-like, etc.
    return re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", task_id or "") is not None


def _safe_task_dir(history_root: Path, task_id: str) -> Path | None:
    if not _safe_task_id(task_id):
        return None

    task_dir = history_root / task_id
    try:
        resolved = task_dir.resolve()
        resolved.relative_to(history_root.resolve())
    except Exception:
        return None

    try:
        if task_dir.is_symlink():
            return None
    except Exception:
        return None

    return task_dir


def _probe_openai_compatible_models(base_url: str, api_key: str) -> Dict[str, Any]:
    """
    Best-effort probe for OpenAI-compatible upstream (/v1/models).
    base_url can be with or without /v1.
    """
    if not base_url:
        return {"ok": False, "error": "base_url 为空"}

    base = base_url.rstrip("/").rstrip("/v1")
    url = f"{base}/v1/models"

    try:
        r = requests.get(url, headers={"Authorization": f"Bearer {api_key}"}, timeout=10)
        ok = r.status_code == 200
        detail = None
        if not ok:
            detail = r.text[:200]
        return {
            "ok": ok,
            "status": r.status_code,
            "url": url,
            "detail": detail,
        }
    except Exception as e:
        return {"ok": False, "url": url, "error": str(e)}


def create_admin_blueprint():
    admin_bp = Blueprint("admin", __name__)

    @admin_bp.before_request
    def _guard():
        return _require_local()

    @admin_bp.route("/admin/health", methods=["GET"])
    def admin_health():
        root = _get_project_root()
        text_cfg = _read_yaml(root / "text_providers.yaml")
        image_cfg = _read_yaml(root / "image_providers.yaml")

        active_text_name = text_cfg.get("active_provider")
        active_image_name = image_cfg.get("active_provider")

        text_provider = (text_cfg.get("providers") or {}).get(active_text_name, {}) if active_text_name else {}
        image_provider = (image_cfg.get("providers") or {}).get(active_image_name, {}) if active_image_name else {}

        def _safe_provider_info(provider: dict) -> dict:
            # Explicit allowlist to avoid accidental leakage (e.g. api_key).
            return {
                "type": provider.get("type"),
                "model": provider.get("model"),
                "base_url": provider.get("base_url", ""),
            }

        probes = {}
        if text_provider.get("type") == "openai_compatible" and text_provider.get("base_url"):
            probes["text_models"] = _probe_openai_compatible_models(
                text_provider.get("base_url", ""),
                text_provider.get("api_key", "")
            )

        if image_provider.get("type") in ("openai_compatible", "image_api") and image_provider.get("base_url"):
            probes["image_models"] = _probe_openai_compatible_models(
                image_provider.get("base_url", ""),
                image_provider.get("api_key", "")
            )

        return jsonify({
            "success": True,
            "time": time.time(),
            "platform": {
                "python": platform.python_version(),
                "system": platform.system(),
                "release": platform.release(),
            },
            "providers": {
                "text": {
                    "active_provider": active_text_name,
                    **_safe_provider_info(text_provider),
                },
                "image": {
                    "active_provider": active_image_name,
                    **_safe_provider_info(image_provider),
                },
            },
            "probes": probes,
        })

    @admin_bp.route("/admin/tasks", methods=["GET"])
    def list_tasks():
        svc = get_image_service()
        tasks = svc.list_tasks()
        return jsonify({"success": True, "tasks": tasks})

    @admin_bp.route("/admin/tasks/<task_id>", methods=["DELETE"])
    def cleanup_task(task_id: str):
        delete_files = request.args.get("delete_files", "false").lower() == "true"

        svc = get_image_service()
        existed = svc.get_task_state(task_id) is not None
        svc.cleanup_task(task_id)

        deleted = False
        error = None
        if delete_files:
            history_root = _get_project_root() / "history"
            history_root.mkdir(parents=True, exist_ok=True)
            task_dir = _safe_task_dir(history_root, task_id)
            try:
                if task_dir and task_dir.exists() and task_dir.is_dir():
                    shutil.rmtree(task_dir)
                    deleted = True
            except Exception as e:
                error = str(e)

        return jsonify({
            "success": True,
            "task_id": task_id,
            "existed_in_memory": existed,
            "deleted_files": deleted,
            "error": error,
        })

    @admin_bp.route("/admin/logs", methods=["GET"])
    def get_logs():
        """
        Read a chunk of the server log file.

        Query:
        - offset: byte offset in file
        - max_bytes: max bytes to return (<= 2MB)
        """
        try:
            offset = int(request.args.get("offset", "0"))
        except Exception:
            offset = 0
        try:
            max_bytes = int(request.args.get("max_bytes", str(128 * 1024)))
        except Exception:
            max_bytes = 128 * 1024

        log_file = _get_log_file()
        chunk = _read_log_chunk(log_file, offset, max_bytes)
        warn_bytes = int(os.environ.get("REDINK_LOG_WARN_BYTES", str(100 * 1024 * 1024)))  # 100MB
        warnings = []
        size = chunk.get("size") or 0
        if warn_bytes > 0 and size > warn_bytes:
            warnings.append({
                "type": "log_too_large",
                "message": f"日志文件过大：{size} bytes，建议轮转（rotate）或缩小日志级别",
                "size": size,
                "threshold": warn_bytes,
            })

        return jsonify({"success": True, "log_file": str(log_file), "warnings": warnings, **chunk})

    @admin_bp.route("/admin/logs/download", methods=["GET"])
    def download_logs():
        log_file = _get_log_file()
        if not log_file.exists():
            return jsonify({"success": False, "error": "日志文件不存在"}), 404
        return send_file(str(log_file), mimetype="text/plain", as_attachment=True, download_name=log_file.name)

    @admin_bp.route("/admin/logs/rotate", methods=["POST"])
    def rotate_logs():
        """
        Force log rotation (best-effort).

        Works when the server uses RotatingFileHandler for REDINK_LOG_FILE.
        """
        import logging as py_logging
        from logging.handlers import RotatingFileHandler

        log_file = _get_log_file().resolve()
        if not log_file.exists():
            return jsonify({"success": False, "rotated": False, "log_file": str(log_file), "error": "日志文件不存在"}), 404

        root_logger = py_logging.getLogger()

        rotated = False
        error = None
        method = None
        backup_file = None

        for h in list(getattr(root_logger, "handlers", [])):
            try:
                if isinstance(h, RotatingFileHandler) and Path(h.baseFilename).resolve() == log_file:
                    try:
                        h.acquire()
                        h.doRollover()
                        rotated = True
                        method = "handler_rollover"
                    finally:
                        h.release()
                    break
            except Exception as e:
                error = str(e)

        # Fallback: Windows 上 debug reloader / 多进程常导致 rename 失败（WinError 32）。
        # 采用“复制备份 + 清空原文件”的方式，避免对正在被写入的文件做 rename。
        if not rotated:
            try:
                ts = time.strftime("%Y%m%d-%H%M%S")
                backup_file = str(log_file.with_name(f"{log_file.name}.{ts}.bak"))
                shutil.copyfile(str(log_file), backup_file)
                # Truncate in place. This usually works even when another process holds the file open.
                with open(log_file, "r+b") as f:
                    f.truncate(0)
                rotated = True
                method = "copy_truncate"
                error = None
            except Exception as e:
                if error is None:
                    error = str(e)

        if not rotated and error is None:
            error = "轮转失败：未找到可用的日志处理器，且备份/清空也失败"

        status = 200 if rotated else 400
        return jsonify({
            "success": rotated,
            "rotated": rotated,
            "method": method,
            "backup_file": backup_file,
            "log_file": str(log_file),
            "error": error,
        }), status

    @admin_bp.route("/admin/history/stats", methods=["GET"])
    def history_stats():
        return jsonify({"success": True, "stats": _history_stats()})

    @admin_bp.route("/admin/history/cleanup", methods=["POST"])
    def history_cleanup():
        """
        Cleanup history task directories.

        Body:
        - delete_orphan_tasks: bool (default false)
        - older_than_days: int (optional)
        - keep_last_n: int (optional, keep most recent N in scope)
        - larger_than_mb: float (optional, only delete dirs >= threshold size)
        - scope: orphan|all (default orphan)
        - dry_run: bool (default true)
        """
        data = request.get_json(silent=True) or {}
        scope = (data.get("scope") or "orphan").strip().lower()  # orphan|all
        delete_orphan_tasks = bool(data.get("delete_orphan_tasks", False))
        dry_run = bool(data.get("dry_run", True))
        older_than_days = data.get("older_than_days", None)
        keep_last_n = data.get("keep_last_n", None)
        larger_than_mb = data.get("larger_than_mb", None)
        try:
            if older_than_days is not None:
                older_than_days = int(older_than_days)
        except Exception:
            older_than_days = None
        try:
            if keep_last_n is not None:
                keep_last_n = int(keep_last_n)
        except Exception:
            keep_last_n = None
        try:
            if larger_than_mb is not None:
                larger_than_mb = float(larger_than_mb)
        except Exception:
            larger_than_mb = None

        if scope not in ("orphan", "all"):
            return jsonify({"success": False, "error": "scope 只能为 orphan 或 all"}), 400

        has_filters = False
        if older_than_days is not None and older_than_days > 0:
            has_filters = True
        if keep_last_n is not None and keep_last_n > 0:
            has_filters = True
        if larger_than_mb is not None and larger_than_mb > 0:
            has_filters = True
        if not delete_orphan_tasks and not has_filters:
            return jsonify({
                "success": False,
                "error": "未指定清理策略：请设置 delete_orphan_tasks=true 或至少指定一个过滤条件（older_than_days/keep_last_n/larger_than_mb）"
            }), 400

        # Selection:
        # - delete_orphan_tasks=true forces orphan selection (even if scope=all)
        # - otherwise, selection follows scope
        effective_scope = "orphan" if delete_orphan_tasks else scope

        root = _get_project_root()
        history_root = root / "history"
        history_root.mkdir(parents=True, exist_ok=True)

        # Extra guardrails for destructive operations
        if not dry_run and effective_scope == "all":
            confirm_any = data.get("confirm_delete_any")
            if confirm_any != "YES_DELETE_ANY_TASKS":
                return jsonify({
                    "success": False,
                    "error": "scope=all 且 dry_run=false 属于高风险操作：请传入 confirm_delete_any='YES_DELETE_ANY_TASKS'"
                }), 400

        # Any destructive orphan cleanup requires explicit confirmation as well.
        if not dry_run and effective_scope == "orphan":
            confirm = data.get("confirm_delete_orphans")
            if confirm != "YES_DELETE_ORPHAN_TASKS":
                return jsonify({
                    "success": False,
                    "error": "删除孤儿任务目录需要确认：请传入 confirm_delete_orphans='YES_DELETE_ORPHAN_TASKS'（并建议先 dry_run）"
                }), 400

        stats = _history_stats()

        # Build metadata map from stats.largest/newest isn't enough; rescan quick for scope decisions.
        task_meta = {}
        referenced_task_ids = set()
        try:
            import json
            idx = history_root / "index.json"
            if idx.exists():
                records = (json.loads(idx.read_text(encoding="utf-8")) or {}).get("records", [])
                for r in records:
                    tid = (r or {}).get("task_id")
                    if tid:
                        referenced_task_ids.add(str(tid))
        except Exception:
            referenced_task_ids = set()

        for p in history_root.iterdir():
            if not p.is_dir():
                continue
            try:
                bytes_ = _dir_size_bytes(p)
                mtime = p.stat().st_mtime
            except Exception:
                bytes_ = 0
                mtime = None
            tid = p.name
            task_meta[tid] = {
                "task_id": tid,
                "bytes": bytes_,
                "mtime": mtime,
                "is_orphan": tid not in referenced_task_ids,
            }

        base_ids = []
        for tid, meta in task_meta.items():
            if effective_scope == "all":
                base_ids.append(tid)
            else:
                if meta.get("is_orphan"):
                    base_ids.append(tid)

        to_delete = set(base_ids)
        kept = []

        # keep_last_n: keep most recent N in the selected scope
        if keep_last_n is not None and keep_last_n > 0:
            ordered = list(base_ids)
            ordered.sort(key=lambda x: ((task_meta.get(x) or {}).get("mtime") or 0), reverse=True)
            kept = ordered[:keep_last_n]
            to_delete.difference_update(set(kept))

        # Apply filters (AND semantics): further narrow down deletions
        if older_than_days is not None and older_than_days > 0:
            threshold = time.time() - older_than_days * 86400
            to_delete = {
                tid for tid in to_delete
                if (((task_meta.get(tid) or {}).get("mtime") or 0) < threshold)
            }

        if larger_than_mb is not None and larger_than_mb > 0:
            threshold_bytes = int(larger_than_mb * 1024 * 1024)
            to_delete = {
                tid for tid in to_delete
                if int((task_meta.get(tid) or {}).get("bytes") or 0) >= threshold_bytes
            }

        deleted = []
        failed = []
        for tid in sorted(to_delete):
            task_dir = _safe_task_dir(history_root, tid)
            if not task_dir or not task_dir.exists() or not task_dir.is_dir():
                continue
            if dry_run:
                deleted.append({"task_id": tid, "dry_run": True, "bytes": (task_meta.get(tid) or {}).get("bytes")})
                continue
            try:
                shutil.rmtree(task_dir)
                deleted.append({"task_id": tid, "dry_run": False, "bytes": (task_meta.get(tid) or {}).get("bytes")})
            except Exception as e:
                failed.append({"task_id": tid, "error": str(e)})

        return jsonify({
            "success": True,
            "scope": scope,
            "effective_scope": effective_scope,
            "dry_run": dry_run,
            "requested": {
                "delete_orphan_tasks": delete_orphan_tasks,
                "older_than_days": older_than_days,
                "keep_last_n": keep_last_n,
                "larger_than_mb": larger_than_mb,
            },
            "kept": kept[:200],
            "deleted": deleted,
            "failed": failed,
        })

    return admin_bp


__all__ = ["create_admin_blueprint"]
