"""
CSS Lab local smoke test.

Runs a short end-to-end check without spawning a long-running server process:
- Probes local CLIProxyAPI (/v1/models)
- Starts the Flask app on an ephemeral HTTP server (thread)
- Calls key admin APIs + outline generation

Usage (PowerShell):
  cd RedInk
  python scripts/smoke_test.py
"""

from __future__ import annotations

import json
import os
import sys
import time
import threading
from typing import Any, Dict, Tuple

import requests
from werkzeug.serving import make_server


def _probe_cliproxy(base_url: str, api_key: str) -> Tuple[bool, Dict[str, Any]]:
    url = base_url.rstrip("/") + "/models"
    try:
        r = requests.get(url, headers={"Authorization": f"Bearer {api_key}"}, timeout=10)
        if r.status_code != 200:
            return False, {"ok": False, "status": r.status_code, "url": url, "detail": r.text[:200]}
        data = r.json()
        ids = [m.get("id") for m in (data.get("data") or []) if isinstance(m, dict)]
        return True, {"ok": True, "status": 200, "url": url, "models_count": len(ids), "models_sample": ids[:10]}
    except Exception as e:
        return False, {"ok": False, "url": url, "error": str(e)}


def _http(method: str, url: str, timeout: int = 30, **kwargs):
    return requests.request(method, url, timeout=timeout, **kwargs)


def main() -> int:
    os.environ.setdefault("PYTHONUTF8", "1")
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")

    # Ensure project root is on sys.path when running from source checkout.
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if project_root not in sys.path:
        sys.path.insert(0, project_root)

    cliproxy_base = os.environ.get("CLIPROXY_BASE_URL", "http://127.0.0.1:8317/v1")
    cliproxy_key = os.environ.get("CLIPROXY_API_KEY", "whoisyourai")

    ok_proxy, proxy_detail = _probe_cliproxy(cliproxy_base, cliproxy_key)

    # Start RedInk HTTP server
    from backend.app import create_app

    app = create_app()
    host = "127.0.0.1"
    port = 12398

    server = make_server(host, port, app)
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    time.sleep(0.5)

    base = f"http://{host}:{port}"
    report: Dict[str, Any] = {
        "cliproxy": proxy_detail,
        "redink": {},
    }

    failed = False
    try:
        # Admin health
        r = _http("GET", f"{base}/api/admin/health")
        report["redink"]["admin_health_status"] = r.status_code
        try:
            report["redink"]["admin_health"] = r.json()
        except Exception:
            report["redink"]["admin_health"] = {"raw": r.text[:300]}
        if r.status_code != 200:
            failed = True

        # Logs: read + rotate
        r = _http("GET", f"{base}/api/admin/logs", params={"offset": 0, "max_bytes": 4096})
        report["redink"]["admin_logs_status"] = r.status_code
        report["redink"]["admin_logs"] = r.json() if r.headers.get("content-type", "").startswith("application/json") else {"raw": r.text[:300]}
        if r.status_code != 200:
            failed = True

        r = _http("POST", f"{base}/api/admin/logs/rotate", json={})
        report["redink"]["admin_logs_rotate_status"] = r.status_code
        report["redink"]["admin_logs_rotate"] = r.json() if r.headers.get("content-type", "").startswith("application/json") else {"raw": r.text[:300]}
        # rotate is best-effort; treat 400 as warning, not a hard failure

        # History: stats + dry-run cleanup
        r = _http("GET", f"{base}/api/admin/history/stats")
        report["redink"]["history_stats_status"] = r.status_code
        report["redink"]["history_stats"] = r.json() if r.headers.get("content-type", "").startswith("application/json") else {"raw": r.text[:300]}
        if r.status_code != 200:
            failed = True

        r = _http(
            "POST",
            f"{base}/api/admin/history/cleanup",
            json={
                "scope": "orphan",
                "delete_orphan_tasks": True,
                "older_than_days": 0,
                "keep_last_n": 0,
                "larger_than_mb": 0,
                "dry_run": True,
            },
        )
        report["redink"]["history_cleanup_status"] = r.status_code
        report["redink"]["history_cleanup"] = r.json() if r.headers.get("content-type", "").startswith("application/json") else {"raw": r.text[:300]}
        if r.status_code != 200:
            failed = True

        # Outline generation (text -> CLIProxyAPI)
        r = _http(
            "POST",
            f"{base}/api/outline",
            json={"topic": "测试主题：5条适合新手的通勤穿搭建议（简短）"},
            timeout=180,
        )
        report["redink"]["outline_status"] = r.status_code
        report["redink"]["outline"] = r.json() if r.headers.get("content-type", "").startswith("application/json") else {"raw": r.text[:300]}
        if r.status_code != 200:
            failed = True
        else:
            if not report["redink"]["outline"].get("success", False):
                failed = True

    finally:
        try:
            server.shutdown()
        except Exception:
            pass

    print(json.dumps(report, ensure_ascii=False, indent=2))

    if not ok_proxy:
        failed = True

    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
