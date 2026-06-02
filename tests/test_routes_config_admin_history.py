from pathlib import Path
import json
import threading
import time
from types import SimpleNamespace
import yaml


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


def test_config_get_requires_auth_when_token_enabled(client, monkeypatch):
    monkeypatch.setenv("REDINK_AUTH_TOKEN", "secret-token")

    resp = client.get("/api/config")
    assert resp.status_code == 401
    data = resp.get_json()
    assert data and data.get("success") is False


def test_config_get_with_auth_returns_masked_config(client, monkeypatch, tmp_path):
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
                    "api_key": "IMAGE_SECRET",
                    "base_url": "https://img.example.com/v1",
                    "model": "m1",
                }
            },
        },
    )
    cr._write_config(
        text_path,
        {
            "active_provider": "txt",
            "providers": {
                "txt": {
                    "type": "openai_compatible",
                    "api_key": "TEXT_SECRET",
                    "base_url": "https://txt.example.com/v1",
                    "model": "m2",
                }
            },
        },
    )

    monkeypatch.setattr(cr, "IMAGE_CONFIG_PATH", image_path)
    monkeypatch.setattr(cr, "TEXT_CONFIG_PATH", text_path)
    monkeypatch.setenv("REDINK_AUTH_TOKEN", "secret-token")

    resp = client.get("/api/config", headers={"Authorization": "Bearer secret-token"})
    assert resp.status_code == 200
    data = resp.get_json()
    assert data and data.get("success") is True
    assert data["config"]["text_generation"]["providers"]["txt"]["api_key"] == ""
    assert data["config"]["image_generation"]["providers"]["img"]["api_key_masked"]


def test_config_get_rejects_invalid_config_file_shape(client, monkeypatch, tmp_path):
    from backend.routes import config_routes as cr

    image_path = tmp_path / "image_providers.yaml"
    text_path = tmp_path / "text_providers.yaml"
    image_path.write_text("- not\n- a\n- mapping\n", encoding="utf-8")
    cr._write_config(text_path, {"active_provider": "txt", "providers": {}})

    monkeypatch.setattr(cr, "IMAGE_CONFIG_PATH", image_path)
    monkeypatch.setattr(cr, "TEXT_CONFIG_PATH", text_path)

    resp = client.get("/api/config")
    assert resp.status_code == 500
    data = resp.get_json()
    assert data and data.get("success") is False
    assert "顶层必须是对象" in data.get("error", "")


def test_config_get_rejects_invalid_providers_shape(client, monkeypatch, tmp_path):
    from backend.routes import config_routes as cr

    image_path = tmp_path / "image_providers.yaml"
    text_path = tmp_path / "text_providers.yaml"
    cr._write_config(image_path, {"active_provider": "img", "providers": ["bad"]})
    cr._write_config(text_path, {"active_provider": "txt", "providers": {}})

    monkeypatch.setattr(cr, "IMAGE_CONFIG_PATH", image_path)
    monkeypatch.setattr(cr, "TEXT_CONFIG_PATH", text_path)

    resp = client.get("/api/config")
    assert resp.status_code == 500
    data = resp.get_json()
    assert data and data.get("success") is False
    assert "providers 必须是对象" in data.get("error", "")


def test_config_route_uses_env_provider_paths(client, monkeypatch, tmp_path):
    from backend.config import Config
    from backend.routes import config_routes as cr

    image_path = tmp_path / "image_providers.yaml"
    text_path = tmp_path / "text_providers.yaml"
    cr._write_config(image_path, {"active_provider": "img-env", "providers": {}})
    cr._write_config(text_path, {"active_provider": "txt-env", "providers": {}})

    monkeypatch.setattr(cr, "IMAGE_CONFIG_PATH", None)
    monkeypatch.setattr(cr, "TEXT_CONFIG_PATH", None)
    monkeypatch.setenv("REDINK_IMAGE_PROVIDERS_PATH", str(image_path))
    monkeypatch.setenv("REDINK_TEXT_PROVIDERS_PATH", str(text_path))
    Config.reload_config()

    resp = client.get("/api/config")

    assert resp.status_code == 200
    data = resp.get_json()
    assert data and data.get("success") is True
    assert data["config"]["image_generation"]["active_provider"] == "img-env"
    assert data["config"]["text_generation"]["active_provider"] == "txt-env"


def test_config_routes_reject_same_text_and_image_config_path(client, monkeypatch, tmp_path):
    from backend.routes import config_routes as cr

    shared_path = tmp_path / "providers.yaml"
    cr._write_config(shared_path, {"active_provider": "shared", "providers": {}})

    monkeypatch.setattr(cr, "IMAGE_CONFIG_PATH", shared_path)
    monkeypatch.setattr(cr, "TEXT_CONFIG_PATH", shared_path)

    resp = client.get("/api/config")
    assert resp.status_code == 500
    assert "不能指向同一个文件" in resp.get_json().get("error", "")

    resp = client.post(
        "/api/config",
        json={
            "image_generation": {
                "active_provider": "img",
                "providers": {"img": {"type": "image_api", "api_key": "secret"}},
            }
        },
    )
    assert resp.status_code == 400
    assert "不能指向同一个文件" in resp.get_json().get("error", "")


def test_admin_health_uses_env_provider_paths(client, monkeypatch, tmp_path):
    from backend.config import Config
    from backend.routes import config_routes as cr

    image_path = tmp_path / "image_providers.yaml"
    text_path = tmp_path / "text_providers.yaml"
    cr._write_config(
        image_path,
        {
            "active_provider": "img-env",
            "providers": {
                "img-env": {"type": "google_genai", "model": "image-model"}
            },
        },
    )
    cr._write_config(
        text_path,
        {
            "active_provider": "txt-env",
            "providers": {
                "txt-env": {"type": "google_gemini", "model": "text-model"}
            },
        },
    )

    monkeypatch.setenv("REDINK_IMAGE_PROVIDERS_PATH", str(image_path))
    monkeypatch.setenv("REDINK_TEXT_PROVIDERS_PATH", str(text_path))
    Config.reload_config()

    resp = client.get("/api/admin/health")

    assert resp.status_code == 200
    data = resp.get_json()
    assert data and data.get("success") is True
    assert data["providers"]["image"]["active_provider"] == "img-env"
    assert data["providers"]["image"]["model"] == "image-model"
    assert data["providers"]["text"]["active_provider"] == "txt-env"
    assert data["providers"]["text"]["model"] == "text-model"


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


def test_config_update_rejects_invalid_provider_structure(client, monkeypatch, tmp_path):
    from backend.routes import config_routes as cr

    image_path = tmp_path / "image_providers.yaml"
    text_path = tmp_path / "text_providers.yaml"
    original = {"active_provider": "img", "providers": {}}
    cr._write_config(image_path, original)
    cr._write_config(text_path, {"active_provider": "txt", "providers": {}})

    monkeypatch.setattr(cr, "IMAGE_CONFIG_PATH", image_path)
    monkeypatch.setattr(cr, "TEXT_CONFIG_PATH", text_path)

    resp = client.post(
        "/api/config",
        json={"image_generation": {"providers": ["not", "a", "mapping"]}},
    )
    assert resp.status_code == 400

    saved = cr._read_config(image_path, {})
    assert saved == original


def test_config_update_validates_all_sections_before_writing(client, monkeypatch, tmp_path):
    from backend.routes import config_routes as cr

    image_path = tmp_path / "image_providers.yaml"
    text_path = tmp_path / "text_providers.yaml"
    original_image = {"active_provider": "img-old", "providers": {"img-old": {"type": "image_api", "api_key": "old"}}}
    original_text = {"active_provider": "txt-old", "providers": {"txt-old": {"type": "openai_compatible", "api_key": "old"}}}
    cr._write_config(image_path, original_image)
    cr._write_config(text_path, original_text)

    monkeypatch.setattr(cr, "IMAGE_CONFIG_PATH", image_path)
    monkeypatch.setattr(cr, "TEXT_CONFIG_PATH", text_path)

    resp = client.post(
        "/api/config",
        json={
            "image_generation": {
                "active_provider": "img-new",
                "providers": {"img-new": {"type": "image_api", "api_key": "new"}},
            },
            "text_generation": {
                "active_provider": "txt-new",
                "providers": {"txt-new": {"type": "image_api", "api_key": "bad"}},
            },
        },
    )

    assert resp.status_code == 400
    assert "服务商类型不支持" in resp.get_json().get("error", "")
    assert cr._read_config(image_path, {}) == original_image
    assert cr._read_config(text_path, {}) == original_text


def test_config_update_rolls_back_first_file_if_second_write_fails(client, monkeypatch, tmp_path):
    from backend.routes import config_routes as cr

    image_path = tmp_path / "image_providers.yaml"
    text_path = tmp_path / "text_providers.yaml"
    original_image = {"active_provider": "img-old", "providers": {"img-old": {"type": "image_api", "api_key": "old"}}}
    original_text = {"active_provider": "txt-old", "providers": {"txt-old": {"type": "openai_compatible", "api_key": "old"}}}
    cr._write_config(image_path, original_image)
    cr._write_config(text_path, original_text)

    monkeypatch.setattr(cr, "IMAGE_CONFIG_PATH", image_path)
    monkeypatch.setattr(cr, "TEXT_CONFIG_PATH", text_path)

    original_write_config = cr._write_config
    write_counts = {"image": 0, "text": 0}

    def flaky_write_config(path, config):
        if Path(path) == image_path:
            write_counts["image"] += 1
        if Path(path) == text_path:
            write_counts["text"] += 1
            raise OSError("simulated text config write failure")
        original_write_config(path, config)

    monkeypatch.setattr(cr, "_write_config", flaky_write_config)

    resp = client.post(
        "/api/config",
        json={
            "image_generation": {
                "active_provider": "img-new",
                "providers": {"img-new": {"type": "image_api", "api_key": "new"}},
            },
            "text_generation": {
                "active_provider": "txt-new",
                "providers": {"txt-new": {"type": "openai_compatible", "api_key": "new"}},
            },
        },
    )

    assert resp.status_code == 500
    assert write_counts == {"image": 2, "text": 1}
    assert cr._read_config(image_path, {}) == original_image
    assert cr._read_config(text_path, {}) == original_text


def test_config_update_rejects_active_provider_missing_from_providers(client, monkeypatch, tmp_path):
    from backend.routes import config_routes as cr

    image_path = tmp_path / "image_providers.yaml"
    text_path = tmp_path / "text_providers.yaml"
    original = {"active_provider": "img", "providers": {"img": {"type": "image_api", "api_key": "secret"}}}
    cr._write_config(image_path, original)
    cr._write_config(text_path, {"active_provider": "txt", "providers": {}})

    monkeypatch.setattr(cr, "IMAGE_CONFIG_PATH", image_path)
    monkeypatch.setattr(cr, "TEXT_CONFIG_PATH", text_path)

    resp = client.post(
        "/api/config",
        json={"image_generation": {"active_provider": "missing", "providers": {}}},
    )

    assert resp.status_code == 400
    data = resp.get_json()
    assert data and "active_provider" in data.get("error", "")
    assert cr._read_config(image_path, {}) == original


def test_config_update_selects_provider_when_active_provider_empty(client, monkeypatch, tmp_path):
    from backend.routes import config_routes as cr

    image_path = tmp_path / "image_providers.yaml"
    text_path = tmp_path / "text_providers.yaml"
    cr._write_config(image_path, {"active_provider": "img", "providers": {}})
    cr._write_config(text_path, {"active_provider": "txt", "providers": {}})

    monkeypatch.setattr(cr, "IMAGE_CONFIG_PATH", image_path)
    monkeypatch.setattr(cr, "TEXT_CONFIG_PATH", text_path)

    resp = client.post(
        "/api/config",
        json={
            "image_generation": {
                "active_provider": "",
                "providers": {
                    "img-next": {
                        "type": "image_api",
                        "api_key": "secret",
                    }
                },
            }
        },
    )

    assert resp.status_code == 200
    saved = cr._read_config(image_path, {})
    assert saved["active_provider"] == "img-next"


def test_config_update_allows_openai_compatible_image_provider(client, monkeypatch, tmp_path):
    from backend.routes import config_routes as cr

    image_path = tmp_path / "image_providers.yaml"
    text_path = tmp_path / "text_providers.yaml"
    cr._write_config(image_path, {"active_provider": "img", "providers": {}})
    cr._write_config(text_path, {"active_provider": "txt", "providers": {}})

    monkeypatch.setattr(cr, "IMAGE_CONFIG_PATH", image_path)
    monkeypatch.setattr(cr, "TEXT_CONFIG_PATH", text_path)

    resp = client.post(
        "/api/config",
        json={
            "image_generation": {
                "active_provider": "img",
                "providers": {"img": {"type": "openai_compatible", "api_key": "secret"}},
            }
        },
    )

    assert resp.status_code == 200
    saved = cr._read_config(image_path, {})
    assert saved["providers"]["img"]["type"] == "openai_compatible"


def test_config_update_rejects_unsupported_provider_type(client, monkeypatch, tmp_path):
    from backend.routes import config_routes as cr

    image_path = tmp_path / "image_providers.yaml"
    text_path = tmp_path / "text_providers.yaml"
    original = {"active_provider": "img", "providers": {}}
    cr._write_config(image_path, original)
    cr._write_config(text_path, {"active_provider": "txt", "providers": {}})

    monkeypatch.setattr(cr, "IMAGE_CONFIG_PATH", image_path)
    monkeypatch.setattr(cr, "TEXT_CONFIG_PATH", text_path)

    resp = client.post(
        "/api/config",
        json={
            "image_generation": {
                "active_provider": "img",
                "providers": {"img": {"type": "google_gemini", "api_key": "secret"}},
            }
        },
    )

    assert resp.status_code == 400
    data = resp.get_json()
    assert data and "服务商类型不支持" in data.get("error", "")
    assert cr._read_config(image_path, {}) == original


def test_config_update_rejects_invalid_base_url_and_endpoint(client, monkeypatch, tmp_path):
    from backend.routes import config_routes as cr

    image_path = tmp_path / "image_providers.yaml"
    text_path = tmp_path / "text_providers.yaml"
    original_image = {"active_provider": "img", "providers": {}}
    original_text = {"active_provider": "txt", "providers": {}}
    cr._write_config(image_path, original_image)
    cr._write_config(text_path, original_text)

    monkeypatch.setattr(cr, "IMAGE_CONFIG_PATH", image_path)
    monkeypatch.setattr(cr, "TEXT_CONFIG_PATH", text_path)

    bad_base = client.post(
        "/api/config",
        json={
            "image_generation": {
                "active_provider": "img",
                "providers": {
                    "img": {
                        "type": "image_api",
                        "api_key": "secret",
                        "base_url": "http://user:pass@example.com/v1",
                    }
                },
            }
        },
    )
    assert bad_base.status_code == 400
    assert "不允许包含用户名或密码" in bad_base.get_json().get("error", "")

    bad_endpoint = client.post(
        "/api/config",
        json={
            "text_generation": {
                "active_provider": "txt",
                "providers": {
                    "txt": {
                        "type": "openai_compatible",
                        "api_key": "secret",
                        "endpoint_type": "https://evil.example/v1/chat/completions",
                    }
                },
            }
        },
    )
    assert bad_endpoint.status_code == 400
    assert "不能是完整 URL" in bad_endpoint.get_json().get("error", "")

    assert cr._read_config(image_path, {}) == original_image
    assert cr._read_config(text_path, {}) == original_text


def test_config_update_normalizes_endpoint_path(client, monkeypatch, tmp_path):
    from backend.routes import config_routes as cr

    image_path = tmp_path / "image_providers.yaml"
    text_path = tmp_path / "text_providers.yaml"
    cr._write_config(image_path, {"active_provider": "img", "providers": {}})
    cr._write_config(text_path, {"active_provider": "txt", "providers": {}})

    monkeypatch.setattr(cr, "IMAGE_CONFIG_PATH", image_path)
    monkeypatch.setattr(cr, "TEXT_CONFIG_PATH", text_path)

    resp = client.post(
        "/api/config",
        json={
            "text_generation": {
                "active_provider": "txt",
                "providers": {
                    "txt": {
                        "type": "openai_compatible",
                        "api_key": "secret",
                        "base_url": "https://api.example.com/v1",
                        "endpoint_type": "v1/chat/completions",
                    }
                },
            }
        },
    )

    assert resp.status_code == 200
    saved = cr._read_config(text_path, {})
    assert saved["providers"]["txt"]["endpoint_type"] == "/v1/chat/completions"


def test_write_config_uses_unique_temp_paths_for_overlapping_writes(monkeypatch, tmp_path):
    from backend.routes import config_routes as cr

    config_path = tmp_path / "providers.yaml"
    replace_sources = []
    replace_lock = threading.Lock()
    start = threading.Barrier(2)

    def fake_replace(src, dst):
        with replace_lock:
            replace_sources.append(Path(src))
        start.wait(timeout=5)
        Path(dst).write_text(Path(src).read_text(encoding="utf-8"), encoding="utf-8")

    monkeypatch.setattr(cr.os, "replace", fake_replace)

    errors = []

    def write_config(name):
        try:
            cr._write_config(config_path, {"active_provider": name, "providers": {}})
        except Exception as exc:
            errors.append(exc)

    threads = [
        threading.Thread(target=write_config, args=("one",)),
        threading.Thread(target=write_config, args=("two",)),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)

    assert errors == []
    assert len(replace_sources) == 2
    assert replace_sources[0] != replace_sources[1]
    assert not list(tmp_path.glob("*.tmp"))


def test_update_provider_config_serializes_read_modify_write(monkeypatch, tmp_path):
    from backend.routes import config_routes as cr

    config_path = tmp_path / "providers.yaml"
    cr._write_config(config_path, {"active_provider": "initial", "providers": {}})

    active_writers = 0
    max_active_writers = 0
    writer_lock = threading.Lock()
    original_write_config = cr._write_config

    def slow_write_config(path, config):
        nonlocal active_writers, max_active_writers
        with writer_lock:
            active_writers += 1
            max_active_writers = max(max_active_writers, active_writers)
        try:
            time.sleep(0.05)
            original_write_config(path, config)
        finally:
            with writer_lock:
                active_writers -= 1

    monkeypatch.setattr(cr, "_write_config", slow_write_config)

    errors = []

    def update_provider(name):
        try:
            cr._update_provider_config(
                config_path,
                {
                    "active_provider": name,
                    "providers": {
                        name: {
                            "type": "image_api",
                            "api_key": f"secret-{name}",
                        }
                    },
                },
            )
        except Exception as exc:
            errors.append(exc)

    threads = [
        threading.Thread(target=update_provider, args=("one",)),
        threading.Thread(target=update_provider, args=("two",)),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)

    assert errors == []
    assert max_active_writers == 1
    saved = cr._read_config(config_path, {})
    assert saved["active_provider"] in {"one", "two"}
    assert set(saved["providers"]) in ({"one"}, {"two"})


def test_google_genai_connection_test_uses_api_key_mode_without_base_url(monkeypatch):
    from backend.routes import config_routes as cr
    from google import genai

    calls = []

    class DummyModels:
        def list(self):
            return ["model"]

    class DummyClient:
        def __init__(self, **kwargs):
            calls.append(kwargs)
            self.models = DummyModels()

    monkeypatch.setattr(genai, "Client", DummyClient)

    result = cr._test_google_genai({"api_key": "key"})

    assert result["success"] is True
    assert calls == [{"api_key": "key", "vertexai": False}]


def test_google_gemini_connection_test_uses_api_key_mode_without_base_url(monkeypatch):
    from backend.routes import config_routes as cr
    from google import genai

    calls = []

    class DummyModels:
        def generate_content(self, **kwargs):
            return SimpleNamespace(text="你好，CSS Lab")

    class DummyClient:
        def __init__(self, **kwargs):
            calls.append(kwargs)
            self.models = DummyModels()

    monkeypatch.setattr(genai, "Client", DummyClient)

    result = cr._test_google_gemini({"api_key": "key", "model": "gemini-test"}, "hello")

    assert result["success"] is True
    assert calls == [{"api_key": "key", "vertexai": False}]


def test_connection_config_loader_uses_provider_category_for_openai_compatible(monkeypatch, tmp_path):
    from backend.routes import config_routes as cr

    text_path = tmp_path / "text.yaml"
    image_path = tmp_path / "image.yaml"
    text_path.write_text(
        yaml.safe_dump({
            "active_provider": "shared",
            "providers": {
                "shared": {
                    "type": "openai_compatible",
                    "api_key": "text-key",
                    "base_url": "https://text.example.com/v1",
                    "model": "text-model",
                    "endpoint_type": "/v1/chat/completions",
                }
            },
        }),
        encoding="utf-8",
    )
    image_path.write_text(
        yaml.safe_dump({
            "active_provider": "shared",
            "providers": {
                "shared": {
                    "type": "openai_compatible",
                    "api_key": "image-key",
                    "base_url": "https://image.example.com/v1",
                    "model": "image-model",
                    "endpoint_type": "/v1/images/generations",
                }
            },
        }),
        encoding="utf-8",
    )

    monkeypatch.setattr(cr, "TEXT_CONFIG_PATH", text_path)
    monkeypatch.setattr(cr, "IMAGE_CONFIG_PATH", image_path)

    config = cr._load_provider_config(
        "openai_compatible",
        "shared",
        {"api_key": None, "base_url": None, "model": None, "endpoint_type": None},
        provider_category="image",
    )

    assert config["api_key"] == "image-key"
    assert config["base_url"] == "https://image.example.com/v1"
    assert config["model"] == "image-model"
    assert config["endpoint_type"] == "/v1/images/generations"


def test_openai_compatible_connection_test_uses_configured_endpoint_type(monkeypatch):
    from backend.routes import config_routes as cr

    calls = []

    class DummyResp:
        status_code = 200

        def json(self):
            return {"choices": [{"message": {"content": "你好，CSS Lab"}}]}

    monkeypatch.setattr(cr, "_normalized_provider_base_url", lambda config: "https://api.example.test")

    def fake_request(method, url, **kwargs):
        calls.append((method, url, kwargs))
        return DummyResp()

    monkeypatch.setattr(cr, "safe_http_request", fake_request)

    result = cr._test_openai_compatible(
        {
            "api_key": "key",
            "model": "model",
            "endpoint_type": "/custom/chat/completions",
        },
        "hello",
    )

    assert result["success"] is True
    assert calls[0][0] == "POST"
    assert calls[0][1] == "https://api.example.test/custom/chat/completions"
    assert calls[0][2]["json"]["model"] == "model"


def test_image_api_connection_test_uses_chat_probe_for_chat_endpoint(monkeypatch):
    from backend.routes import config_routes as cr

    calls = []

    class DummyResp:
        status_code = 200

        def json(self):
            return {"choices": [{"message": {"content": "你好，CSS Lab"}}]}

    monkeypatch.setattr(cr, "_normalized_provider_base_url", lambda config: "https://api.example.test")

    def fake_request(method, url, **kwargs):
        calls.append((method, url, kwargs))
        return DummyResp()

    monkeypatch.setattr(cr, "safe_http_request", fake_request)

    result = cr._test_image_api(
        {
            "api_key": "key",
            "model": "image-chat-model",
            "endpoint_type": "/v1/chat/completions",
        }
    )

    assert result["success"] is True
    assert calls[0][0] == "POST"
    assert calls[0][1] == "https://api.example.test/v1/chat/completions"
    assert calls[0][2]["json"]["model"] == "image-chat-model"


def test_openai_compatible_image_connection_routes_to_image_probe(monkeypatch):
    from backend.routes import config_routes as cr

    calls = []

    def fake_image_api(config):
        calls.append(("image", config))
        return {"success": True, "message": "image ok"}

    def fake_text_api(config, test_prompt):
        calls.append(("text", config, test_prompt))
        return {"success": True, "message": "text ok"}

    monkeypatch.setattr(cr, "_test_image_api", fake_image_api)
    monkeypatch.setattr(cr, "_test_openai_compatible", fake_text_api)

    result = cr._test_provider_connection(
        "openai_compatible",
        {"api_key": "key"},
        provider_category="image",
    )

    assert result == {"success": True, "message": "image ok"}
    assert calls == [("image", {"api_key": "key"})]


def test_admin_endpoints_are_local_only_and_work_in_tests(client, monkeypatch):
    import backend.routes.admin_routes as ar

    class DummyResp:
        def __init__(self, status_code=200, text="OK"):
            self.status_code = status_code
            self.text = text

    monkeypatch.setattr(ar, "safe_http_request", lambda *args, **kwargs: DummyResp(200, "OK"))

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


def test_admin_ignores_spoofed_xff_by_default(client, monkeypatch):
    monkeypatch.delenv("REDINK_ADMIN_TRUST_XFF", raising=False)
    monkeypatch.delenv("REDINK_ADMIN_ALLOW_REMOTE", raising=False)
    monkeypatch.delenv("REDINK_ADMIN_TRUST_PRIVATE", raising=False)
    monkeypatch.setenv("REDINK_ALLOW_UNAUTH_REMOTE", "1")

    resp = client.get(
        "/api/admin/health",
        environ_base={"REMOTE_ADDR": "203.0.113.10"},
        headers={"X-Forwarded-For": "127.0.0.1"},
    )

    assert resp.status_code == 403
    data = resp.get_json()
    assert data and data.get("success") is False
    assert "默认仅允许本机访问" in data.get("error", "")


def test_admin_trust_xff_requires_auth_token(client, monkeypatch):
    monkeypatch.setenv("REDINK_ADMIN_TRUST_XFF", "1")
    monkeypatch.delenv("REDINK_AUTH_TOKEN", raising=False)

    resp = client.get(
        "/api/admin/health",
        environ_base={"REMOTE_ADDR": "203.0.113.10"},
        headers={"X-Forwarded-For": "127.0.0.1"},
    )

    assert resp.status_code == 403
    data = resp.get_json()
    assert data and data.get("success") is False
    assert "REDINK_AUTH_TOKEN" in data.get("error", "")


def test_admin_trust_xff_uses_original_client_ip(client, monkeypatch):
    monkeypatch.setenv("REDINK_ADMIN_TRUST_XFF", "1")
    monkeypatch.setenv("REDINK_AUTH_TOKEN", "secret-token")

    resp = client.get(
        "/api/admin/health",
        environ_base={"REMOTE_ADDR": "127.0.0.1"},
        headers={
            "Authorization": "Bearer secret-token",
            "X-Forwarded-For": "203.0.113.10, 127.0.0.1",
        },
    )

    assert resp.status_code == 403
    data = resp.get_json()
    assert data and data.get("success") is False
    assert "默认仅允许本机访问" in data.get("error", "")


def test_admin_trust_xff_allows_forwarded_loopback_with_auth(client, monkeypatch):
    monkeypatch.setenv("REDINK_ADMIN_TRUST_XFF", "1")
    monkeypatch.setenv("REDINK_AUTH_TOKEN", "secret-token")

    resp = client.get(
        "/api/admin/health",
        environ_base={"REMOTE_ADDR": "203.0.113.10"},
        headers={
            "Authorization": "Bearer secret-token",
            "X-Forwarded-For": "127.0.0.1",
        },
    )

    assert resp.status_code == 200
    data = resp.get_json()
    assert data and data.get("success") is True


def test_admin_logs_tolerates_invalid_warn_threshold(client, monkeypatch):
    monkeypatch.setenv("REDINK_LOG_WARN_BYTES", "not-an-int")

    resp = client.get("/api/admin/logs?offset=0&max_bytes=1024")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data and data.get("success") is True


def test_admin_task_delete_files_refuses_referenced_history_dir(client, monkeypatch, tmp_path):
    import backend.routes.admin_routes as ar

    monkeypatch.setattr(ar, "_get_project_root", lambda: tmp_path)

    history_root = tmp_path / "history"
    history_root.mkdir()
    task_id = "task_referenced"
    record_id = "record_1"
    (history_root / task_id).mkdir()
    (history_root / task_id / "0.png").write_bytes(b"image")
    (history_root / "index.json").write_text(
        json.dumps({"records": [{"id": record_id, "task_id": task_id}]}),
        encoding="utf-8",
    )
    (history_root / f"{record_id}.json").write_text(
        json.dumps({"images": {"task_id": task_id}}),
        encoding="utf-8",
    )

    resp = client.delete(f"/api/admin/tasks/{task_id}?delete_files=true")

    assert resp.status_code == 409
    data = resp.get_json()
    assert data and data.get("success") is False
    assert data.get("referenced") is True
    assert (history_root / task_id / "0.png").exists()


def test_admin_task_delete_files_can_force_referenced_history_dir(client, monkeypatch, tmp_path):
    import backend.routes.admin_routes as ar

    monkeypatch.setattr(ar, "_get_project_root", lambda: tmp_path)

    history_root = tmp_path / "history"
    history_root.mkdir()
    task_id = "task_referenced_force"
    (history_root / task_id).mkdir()
    (history_root / task_id / "0.png").write_bytes(b"image")
    (history_root / "index.json").write_text(
        json.dumps({"records": [{"id": "record_1", "task_id": task_id}]}),
        encoding="utf-8",
    )

    resp = client.delete(
        f"/api/admin/tasks/{task_id}?delete_files=true&confirm_delete_referenced=YES_DELETE_REFERENCED_TASK"
    )

    assert resp.status_code == 200
    data = resp.get_json()
    assert data and data.get("success") is True
    assert data.get("deleted_files") is True
    assert not (history_root / task_id).exists()


def test_admin_history_cleanup_uses_detail_task_references(client, monkeypatch, tmp_path):
    import backend.routes.admin_routes as ar

    monkeypatch.setattr(ar, "_get_project_root", lambda: tmp_path)

    history_root = tmp_path / "history"
    history_root.mkdir()
    task_id = "task_detail_ref"
    record_id = "record_detail_ref"
    (history_root / task_id).mkdir()
    (history_root / task_id / "0.png").write_bytes(b"image")
    (history_root / "index.json").write_text(
        json.dumps({"records": [{"id": record_id}]}),
        encoding="utf-8",
    )
    (history_root / f"{record_id}.json").write_text(
        json.dumps({"images": {"task_id": task_id}}),
        encoding="utf-8",
    )

    stats_resp = client.get("/api/admin/history/stats")
    assert stats_resp.status_code == 200
    stats = stats_resp.get_json()["stats"]
    assert task_id not in stats["orphan_task_dirs"]

    cleanup_resp = client.post(
        "/api/admin/history/cleanup",
        json={"delete_orphan_tasks": True, "dry_run": True},
    )

    assert cleanup_resp.status_code == 200
    data = cleanup_resp.get_json()
    assert data and data.get("success") is True
    assert all(item.get("task_id") != task_id for item in data.get("deleted", []))
    assert (history_root / task_id / "0.png").exists()


def test_admin_history_stats_ignores_unsafe_referenced_task_ids(client, monkeypatch, tmp_path):
    import backend.routes.admin_routes as ar

    monkeypatch.setattr(ar, "_get_project_root", lambda: tmp_path)

    history_root = tmp_path / "history"
    history_root.mkdir()
    (history_root / "index.json").write_text(
        json.dumps({"records": [{"id": "record_unsafe", "task_id": "../outside"}]}),
        encoding="utf-8",
    )
    (history_root / "record_unsafe.json").write_text(
        json.dumps({"images": {"task_id": "../outside-detail"}}),
        encoding="utf-8",
    )

    resp = client.get("/api/admin/history/stats")

    assert resp.status_code == 200
    stats = resp.get_json()["stats"]
    assert "../outside" not in stats["referenced_missing_task_dirs"]
    assert "../outside-detail" not in stats["referenced_missing_task_dirs"]


def test_history_list_rejects_invalid_pagination(client):
    cases = [
        "/api/history?page=bad&page_size=20",
        "/api/history?page=0&page_size=20",
        "/api/history?page=1&page_size=0",
        "/api/history?page=1&page_size=101",
        "/api/history?page=1&page_size=20&status=unknown",
    ]

    for path in cases:
        resp = client.get(path)
        assert resp.status_code == 400
        data = resp.get_json()
        assert data and data.get("success") is False


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


def test_history_download_zip_rejects_oversized_source_images(client, history_service, monkeypatch):
    import backend.routes.history_routes as hr
    import backend.services.history as hs_mod

    monkeypatch.setattr(hs_mod, "_service_instance", history_service)
    monkeypatch.setattr(hr.Config, "MAX_HISTORY_ZIP_SOURCE_BYTES", 4)

    task_id = "task_bigzip"
    outline = {"raw": "raw outline", "pages": [{"index": 0, "type": "cover", "content": "封面"}]}
    resp = client.post("/api/history", json={"topic": "测试标题", "outline": outline, "task_id": task_id})
    assert resp.status_code == 200
    record_id = resp.get_json()["record_id"]

    resp = client.put(
        f"/api/history/{record_id}",
        json={"images": {"task_id": task_id, "generated": ["0.png"]}, "status": "completed"},
    )
    assert resp.status_code == 200

    task_dir = Path(history_service.history_dir) / task_id
    task_dir.mkdir(parents=True, exist_ok=True)
    (task_dir / "0.png").write_bytes(b"too-large")

    resp = client.get(f"/api/history/{record_id}/download")

    assert resp.status_code == 413
    data = resp.get_json()
    assert data and data.get("success") is False
    assert "超过下载限制" in data.get("error", "")


def test_history_download_zip_caps_long_download_filename(client, history_service, monkeypatch):
    import backend.services.history as hs_mod

    monkeypatch.setattr(hs_mod, "_service_instance", history_service)

    task_id = "task_longtitle"
    outline = {"raw": "raw outline", "pages": [{"index": 0, "type": "cover", "content": "封面"}]}
    title = "标题" * 200

    resp = client.post("/api/history", json={"topic": title, "outline": outline, "task_id": task_id})
    assert resp.status_code == 200
    record_id = resp.get_json()["record_id"]

    resp = client.put(
        f"/api/history/{record_id}",
        json={"images": {"task_id": task_id, "generated": ["0.png"]}, "status": "completed"},
    )
    assert resp.status_code == 200

    task_dir = Path(history_service.history_dir) / task_id
    task_dir.mkdir(parents=True, exist_ok=True)
    (task_dir / "0.png").write_bytes(b"not-a-real-png")

    resp = client.get(f"/api/history/{record_id}/download")

    assert resp.status_code == 200
    assert len(resp.headers["Content-Disposition"]) < 400
    assert resp.headers["Content-Disposition"].endswith(".zip")


def test_history_create_rejects_invalid_outline_shape(client):
    resp = client.post("/api/history", json={"topic": "标题", "outline": "not-object"})
    assert resp.status_code == 400
    data = resp.get_json()
    assert data and data.get("success") is False


def test_history_create_rejects_invalid_outline_pages_shape(client):
    resp = client.post(
        "/api/history",
        json={"topic": "标题", "outline": {"raw": "x", "pages": "not-list"}},
    )
    assert resp.status_code == 400
    data = resp.get_json()
    assert data and data.get("success") is False


def test_history_create_rejects_invalid_outline_page_entries(client):
    cases = [
        ({"raw": "x", "pages": ["bad-page"]}, "outline.pages 中的每一项都必须是 JSON object"),
        ({"raw": "x", "pages": [{"index": -1, "type": "cover", "content": "封面"}]}, "outline.pages 中的 index 必须是非负整数"),
        ({"raw": "x", "pages": [{"index": 0, "type": "cover", "content": 123}]}, "outline.pages 中的 content 必须是字符串"),
        ({"raw": "x", "pages": [{"index": 0, "type": 123, "content": "封面"}]}, "outline.pages 中的 type 必须是字符串"),
        ({"raw": "x", "pages": [{"index": 0, "type": "cover", "content": "封面"}, {"index": 0, "type": "content", "content": "重复"}]}, "outline.pages 中的 index 不能重复"),
        ({"raw": "x", "pages": [{"index": 0, "type": "cover", "content": "封面"}, {"index": 2, "type": "content", "content": "跳号"}]}, "outline.pages 中的 index 必须从 0 开始连续"),
    ]

    for outline, expected_error in cases:
        resp = client.post("/api/history", json={"topic": "标题", "outline": outline})
        assert resp.status_code == 400
        data = resp.get_json()
        assert data and data.get("success") is False
        assert expected_error in data.get("error", "")


def test_history_update_rejects_unsafe_images_payload(client, history_service, monkeypatch):
    import backend.services.history as hs_mod

    monkeypatch.setattr(hs_mod, "_service_instance", history_service)

    outline = {"raw": "raw outline", "pages": [{"index": 0, "type": "cover", "content": "封面"}]}
    resp = client.post("/api/history", json={"topic": "测试标题", "outline": outline, "task_id": "task_12345678"})
    assert resp.status_code == 200
    record_id = resp.get_json()["record_id"]

    resp = client.put(
        f"/api/history/{record_id}",
        json={"images": {"task_id": "task_12345678", "generated": ["../evil.png"]}},
    )
    assert resp.status_code == 400

    record = history_service.get_record(record_id)
    assert record["images"]["generated"] == []


def test_history_update_rejects_invalid_outline_pages(client, history_service, monkeypatch):
    import backend.services.history as hs_mod

    monkeypatch.setattr(hs_mod, "_service_instance", history_service)

    outline = {"raw": "raw outline", "pages": [{"index": 0, "type": "cover", "content": "封面"}]}
    resp = client.post("/api/history", json={"topic": "测试标题", "outline": outline, "task_id": "task_12345678"})
    assert resp.status_code == 200
    record_id = resp.get_json()["record_id"]

    cases = [
        ({"raw": "raw outline", "pages": "bad"}, "outline.pages 不能为空且必须是数组"),
        ({"raw": "raw outline", "pages": []}, "outline.pages 不能为空且必须是数组"),
        ({"raw": "raw outline", "pages": ["bad"]}, "outline.pages 中的每一项都必须是 JSON object"),
        ({"raw": "raw outline", "pages": [{"index": -1, "type": "cover", "content": "封面"}]}, "outline.pages 中的 index 必须是非负整数"),
        ({"raw": "raw outline", "pages": [{"index": 0, "type": "cover", "content": "封面"}, {"index": 2, "type": "content", "content": "跳号"}]}, "outline.pages 中的 index 必须从 0 开始连续"),
    ]

    for bad_outline, expected_error in cases:
        resp = client.put(f"/api/history/{record_id}", json={"outline": bad_outline})
        assert resp.status_code == 400
        data = resp.get_json()
        assert data and data.get("success") is False
        assert expected_error in data.get("error", "")
