from pathlib import Path


def test_config_get_masks_api_key(client, monkeypatch, tmp_path):
    from backend.routes import config_routes as cr

    image_cfg = {
        "active_provider": "img",
        "providers": {
            "img": {
                "type": "image_api",
                "api_key": "sk-image-1234567890abcdef",
                "base_url": "https://img.example.com/v1",
                "model": "m1",
            }
        },
    }
    text_cfg = {
        "active_provider": "txt",
        "providers": {
            "txt": {
                "type": "openai_compatible",
                "api_key": "sk-text-1234567890abcdef",
                "base_url": "https://txt.example.com/v1",
                "model": "m2",
            }
        },
    }

    image_path = tmp_path / "image_providers.yaml"
    text_path = tmp_path / "text_providers.yaml"
    cr._write_config(image_path, image_cfg)
    cr._write_config(text_path, text_cfg)

    monkeypatch.setattr(cr, "IMAGE_CONFIG_PATH", image_path)
    monkeypatch.setattr(cr, "TEXT_CONFIG_PATH", text_path)

    resp = client.get("/api/config")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data and data.get("success") is True

    providers = data["config"]["text_generation"]["providers"]
    assert providers["txt"]["api_key"] == ""
    assert providers["txt"]["api_key_masked"]


def test_config_update_preserves_existing_api_key_when_blank(client, monkeypatch, tmp_path):
    from backend.routes import config_routes as cr

    image_path = tmp_path / "image_providers.yaml"
    text_path = tmp_path / "text_providers.yaml"

    cr._write_config(
        image_path,
        {
            "active_provider": "img",
            "providers": {
                "img": {
                    "type": "image_api",
                    "api_key": "SECRET_IMAGE_KEY",
                    "base_url": "https://img.example.com/v1",
                    "model": "m1",
                }
            },
        },
    )
    cr._write_config(text_path, {"active_provider": "txt", "providers": {}})

    monkeypatch.setattr(cr, "IMAGE_CONFIG_PATH", image_path)
    monkeypatch.setattr(cr, "TEXT_CONFIG_PATH", text_path)

    resp = client.post(
        "/api/config",
        json={
            "image_generation": {
                "active_provider": "img",
                "providers": {
                    "img": {
                        "type": "image_api",
                        "api_key": "",
                        "base_url": "https://img.example.com/v1",
                        "model": "m2",
                    }
                },
            }
        },
    )
    assert resp.status_code == 200

    saved = cr._read_config(image_path, {"providers": {}})
    assert saved["providers"]["img"]["api_key"] == "SECRET_IMAGE_KEY"
    assert saved["providers"]["img"]["model"] == "m2"


def test_admin_endpoints_are_local_only_and_work_in_tests(client, monkeypatch):
    import backend.routes.admin_routes as ar

    class DummyResp:
        def __init__(self, status_code=200, text="OK"):
            self.status_code = status_code
            self.text = text

    monkeypatch.setattr(ar.requests, "get", lambda *args, **kwargs: DummyResp(200, "OK"))

    resp = client.get("/api/admin/health")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data and data.get("success") is True

    resp = client.get("/api/admin/logs?offset=0&max_bytes=1024")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data and data.get("success") is True
    assert "content" in data

    resp = client.post("/api/admin/history/cleanup", json={"delete_orphan_tasks": True, "dry_run": True})
    assert resp.status_code == 200
    data = resp.get_json()
    assert data and data.get("success") is True
    assert data.get("dry_run") is True


def test_history_crud_and_download_zip(client, history_service, monkeypatch):
    import backend.services.history as hs_mod

    monkeypatch.setattr(hs_mod, "_service_instance", history_service)

    task_id = "task_12345678"
    outline = {"raw": "raw outline", "pages": [{"index": 0, "type": "cover", "content": "封面"}]}

    resp = client.post("/api/history", json={"topic": "测试标题", "outline": outline, "task_id": task_id})
    assert resp.status_code == 200
    record_id = resp.get_json()["record_id"]

    resp = client.get(f"/api/history/{record_id}/exists")
    assert resp.status_code == 200
    assert resp.get_json().get("exists") is True

    # Attach images/content to enable ZIP download metadata.
    resp = client.put(
        f"/api/history/{record_id}",
        json={
            "images": {"task_id": task_id, "generated": ["0.png"]},
            "status": "completed",
            "thumbnail": "0.png",
            "content": {"titles": ["t1"], "copywriting": "cw", "tags": ["a", "b"]},
        },
    )
    assert resp.status_code == 200

    task_dir = Path(history_service.history_dir) / task_id
    task_dir.mkdir(parents=True, exist_ok=True)
    (task_dir / "0.png").write_bytes(b"not-a-real-png")

    resp = client.get(f"/api/history/{record_id}/download")
    assert resp.status_code == 200
    assert resp.mimetype == "application/zip"
    assert resp.data[:2] == b"PK"
