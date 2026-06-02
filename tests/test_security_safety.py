import json
import os
import socket
import uuid
import base64
from requests import Request
from pathlib import Path

import pytest


def test_generated_task_ids_use_full_uuid_entropy():
    from backend.services.image import ImageService, new_task_id

    task_id = new_task_id()

    assert task_id.startswith("task_")
    assert len(task_id) == len("task_") + 32
    assert ImageService._is_safe_task_id(task_id)


def test_history_service_rejects_record_id_traversal(temp_history_dir):
    from backend.services.history import HistoryService

    service = HistoryService()
    service.history_dir = temp_history_dir
    service.index_file = os.path.join(temp_history_dir, "index.json")
    service._init_index()

    stem = f"outside_{uuid.uuid4().hex}"
    outside_path = Path(temp_history_dir).parent / f"{stem}.json"
    outside_path.write_text(json.dumps({"pwn": True}), encoding="utf-8")
    try:
        assert service.get_record(f"../{stem}") is None
        assert service.get_record(f"..\\{stem}") is None
        assert service.update_record(f"../{stem}", status="completed") is False
        assert service.delete_record(f"..\\{stem}") is False
    finally:
        try:
            outside_path.unlink(missing_ok=True)
        except Exception:
            pass


def test_generate_rejects_unsafe_task_id(client, sample_pages):
    resp = client.post(
        "/api/generate",
        json={
            "pages": sample_pages,
            "task_id": "..\\evil",
            "full_outline": "",
            "user_images": [],
        },
    )
    assert resp.status_code == 400
    data = resp.get_json()
    assert data and data.get("success") is False


def test_image_route_serves_safe_jpeg_files(client):
    history_root = Path(__file__).parent.parent / "history"
    task_id = f"task_testjpg_{uuid.uuid4().hex[:8]}"
    task_dir = history_root / task_id
    task_dir.mkdir(parents=True, exist_ok=True)
    try:
        (task_dir / "0.jpg").write_bytes(b"jpeg")

        resp = client.get(f"/api/images/{task_id}/0.jpg?thumbnail=false")

        assert resp.status_code == 200
        assert resp.mimetype == "image/jpeg"
        assert resp.data == b"jpeg"
    finally:
        try:
            (task_dir / "0.jpg").unlink(missing_ok=True)
            task_dir.rmdir()
        except Exception:
            pass


def test_image_route_serves_safe_jpeg_thumbnails(client):
    history_root = Path(__file__).parent.parent / "history"
    task_id = f"task_testthumbjpg_{uuid.uuid4().hex[:8]}"
    task_dir = history_root / task_id
    task_dir.mkdir(parents=True, exist_ok=True)
    try:
        (task_dir / "0.jpg").write_bytes(b"original")
        (task_dir / "thumb_0.jpg").write_bytes(b"thumb")

        resp = client.get(f"/api/images/{task_id}/0.jpg")

        assert resp.status_code == 200
        assert resp.mimetype == "image/jpeg"
        assert resp.data == b"thumb"
    finally:
        try:
            (task_dir / "0.jpg").unlink(missing_ok=True)
            (task_dir / "thumb_0.jpg").unlink(missing_ok=True)
            task_dir.rmdir()
        except Exception:
            pass


def test_image_route_requires_auth_when_token_enabled(client, monkeypatch):
    history_root = Path(__file__).parent.parent / "history"
    task_id = f"task_authimg_{uuid.uuid4().hex[:8]}"
    task_dir = history_root / task_id
    task_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("REDINK_AUTH_TOKEN", "secret-token")
    try:
        (task_dir / "0.jpg").write_bytes(b"jpeg")

        resp = client.get(f"/api/images/{task_id}/0.jpg?thumbnail=false")

        assert resp.status_code == 401
        data = resp.get_json()
        assert data and data.get("success") is False
    finally:
        try:
            (task_dir / "0.jpg").unlink(missing_ok=True)
            task_dir.rmdir()
        except Exception:
            pass


def test_image_route_accepts_bearer_auth_when_token_enabled(client, monkeypatch):
    history_root = Path(__file__).parent.parent / "history"
    task_id = f"task_bearerimg_{uuid.uuid4().hex[:8]}"
    task_dir = history_root / task_id
    task_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("REDINK_AUTH_TOKEN", "secret-token")
    try:
        (task_dir / "0.jpg").write_bytes(b"jpeg")

        resp = client.get(
            f"/api/images/{task_id}/0.jpg?thumbnail=false",
            headers={"Authorization": "Bearer secret-token"},
        )

        assert resp.status_code == 200
        assert resp.data == b"jpeg"
    finally:
        try:
            (task_dir / "0.jpg").unlink(missing_ok=True)
            task_dir.rmdir()
        except Exception:
            pass


def test_image_route_accepts_scoped_cookie_when_token_enabled(client, monkeypatch):
    history_root = Path(__file__).parent.parent / "history"
    task_id = f"task_cookieimg_{uuid.uuid4().hex[:8]}"
    task_dir = history_root / task_id
    task_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("REDINK_AUTH_TOKEN", "secret-token")
    try:
        (task_dir / "0.jpg").write_bytes(b"jpeg")
        client.set_cookie("redink_auth_token", "secret-token", path="/api/images")

        resp = client.get(f"/api/images/{task_id}/0.jpg?thumbnail=false")

        assert resp.status_code == 200
        assert resp.data == b"jpeg"
    finally:
        try:
            (task_dir / "0.jpg").unlink(missing_ok=True)
            task_dir.rmdir()
        except Exception:
            pass


def test_image_route_rejects_non_image_extension(client):
    resp = client.get("/api/images/task_abc/0.txt")

    assert resp.status_code == 404
    data = resp.get_json()
    assert data and data.get("success") is False


class _FakeImageResponse:
    def __init__(self, status_code=200, headers=None, chunks=None):
        self.status_code = status_code
        self.headers = headers or {}
        self._chunks = chunks or [b"image-bytes"]
        self.closed = False

    def iter_content(self, chunk_size=65536):
        yield from self._chunks

    def close(self):
        self.closed = True


def _patch_dns(monkeypatch, host_to_ip):
    def fake_getaddrinfo(host, *args, **kwargs):
        ip = host_to_ip[host]
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, 443))]

    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)


def test_safe_download_image_allows_public_http_image(monkeypatch):
    from backend.utils.remote_image import safe_download_image

    _patch_dns(monkeypatch, {"cdn.example.com": "93.184.216.34"})

    def fake_request(method, url, **kwargs):
        assert method == "GET"
        assert url == "https://cdn.example.com/image.png"
        assert kwargs["stream"] is True
        assert kwargs["allow_redirects"] is False
        return _FakeImageResponse(chunks=[b"abc", b"123"])

    monkeypatch.setattr("backend.utils.remote_image.safe_http_request", fake_request)

    assert safe_download_image("https://cdn.example.com/image.png") == b"abc123"


def test_safe_http_request_rejects_dns_rebinding(monkeypatch):
    from backend.utils.remote_image import safe_http_request

    resolutions = iter(["93.184.216.34", "127.0.0.1"])

    def fake_getaddrinfo(host, *args, **kwargs):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (next(resolutions), 443))]

    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)

    with pytest.raises(ValueError, match="非公网地址"):
        safe_http_request("GET", "https://cdn.example.com/image.png")


def test_safe_http_request_requires_modern_requests_adapter_api():
    from requests.adapters import HTTPAdapter

    assert hasattr(HTTPAdapter, "build_connection_pool_key_attributes")
    assert hasattr(HTTPAdapter, "get_connection_with_tls_context")


def test_safe_http_request_pins_validated_ip_and_preserves_host(monkeypatch):
    from backend.utils.remote_image import _PinnedIpAdapter, safe_http_request

    _patch_dns(monkeypatch, {"api.example.com": "93.184.216.34"})
    captured = {}

    class FakeSession:
        def __init__(self):
            self.trust_env = True
            self.mounted = {}

        def mount(self, prefix, adapter):
            self.mounted[prefix] = adapter

        def request(self, method, url, **kwargs):
            captured["method"] = method
            captured["url"] = url
            captured["kwargs"] = kwargs
            captured["trust_env"] = self.trust_env
            captured["mounted"] = self.mounted
            return _FakeImageResponse()

        def close(self):
            captured["closed"] = True

    monkeypatch.setattr("backend.utils.remote_image.requests.Session", FakeSession)

    response = safe_http_request(
        "POST",
        "https://api.example.com/v1/chat/completions",
        headers={"Authorization": "Bearer sk-test", "Host": "evil.example.net"},
        json={"ok": True},
        timeout=30,
    )

    assert response.status_code == 200
    assert captured["method"] == "POST"
    assert captured["url"] == "https://api.example.com/v1/chat/completions"
    assert captured["kwargs"]["headers"]["Host"] == "api.example.com"
    assert captured["kwargs"]["headers"]["Authorization"] == "Bearer sk-test"
    assert captured["kwargs"]["allow_redirects"] is False
    assert captured["trust_env"] is False
    assert captured["closed"] is True
    adapter = captured["mounted"]["https://"]
    assert isinstance(adapter, _PinnedIpAdapter)
    assert adapter._pinned_ip == "93.184.216.34"
    assert adapter._original_hostname == "api.example.com"


def test_pinned_ip_adapter_uses_vetted_ip_for_connection_pool():
    from backend.utils.remote_image import _PinnedIpAdapter

    prepared = Request("GET", "https://api.example.com/v1/models").prepare()
    adapter = _PinnedIpAdapter(
        original_hostname="api.example.com",
        pinned_ip="93.184.216.34",
    )

    host_params, pool_kwargs = adapter.build_connection_pool_key_attributes(
        prepared,
        verify=True,
    )

    assert host_params["host"] == "93.184.216.34"
    assert pool_kwargs["assert_hostname"] == "api.example.com"
    assert pool_kwargs["server_hostname"] == "api.example.com"


def test_safe_http_request_rejects_proxy_override(monkeypatch):
    from backend.utils.remote_image import safe_http_request

    _patch_dns(monkeypatch, {"api.example.com": "93.184.216.34"})

    with pytest.raises(ValueError, match="不允许使用代理请求"):
        safe_http_request(
            "GET",
            "https://api.example.com/v1/models",
            proxies={"https": "http://proxy.example.com:8080"},
        )


def test_safe_http_request_rejects_automatic_redirects(monkeypatch):
    from backend.utils.remote_image import safe_http_request

    _patch_dns(monkeypatch, {"api.example.com": "93.184.216.34"})

    with pytest.raises(ValueError, match="不允许自动跟随重定向"):
        safe_http_request(
            "GET",
            "https://api.example.com/v1/models",
            allow_redirects=True,
        )


@pytest.mark.parametrize("hostname,ip", [
    ("localhost", "127.0.0.1"),
    ("metadata.internal", "169.254.169.254"),
    ("router.local", "192.168.1.1"),
])
def test_safe_download_image_rejects_non_public_addresses(monkeypatch, hostname, ip):
    from backend.utils.remote_image import safe_download_image

    _patch_dns(monkeypatch, {hostname: ip})

    def fake_request(*args, **kwargs):
        raise AssertionError("safe_http_request must not be called for blocked addresses")

    monkeypatch.setattr("backend.utils.remote_image.safe_http_request", fake_request)

    with pytest.raises(ValueError, match="非公网地址"):
        safe_download_image(f"https://{hostname}/image.png")


def test_safe_download_image_allows_private_addresses_when_opted_in(monkeypatch):
    from backend.utils.remote_image import safe_download_image

    _patch_dns(monkeypatch, {"router.local": "192.168.1.1"})
    captured = {}

    def fake_request(method, url, **kwargs):
        captured["allow_private"] = kwargs.get("allow_private")
        return _FakeImageResponse(chunks=[b"private-image"])

    monkeypatch.setattr("backend.utils.remote_image.safe_http_request", fake_request)

    assert safe_download_image("http://router.local/image.png", allow_private=True) == b"private-image"
    assert captured["allow_private"] is True


def test_safe_download_image_revalidates_redirect_targets(monkeypatch):
    from backend.utils.remote_image import safe_download_image

    _patch_dns(monkeypatch, {
        "cdn.example.com": "93.184.216.34",
        "localhost": "127.0.0.1",
    })

    calls = []

    def fake_request(method, url, **kwargs):
        calls.append(url)
        return _FakeImageResponse(status_code=302, headers={"Location": "http://localhost/private.png"})

    monkeypatch.setattr("backend.utils.remote_image.safe_http_request", fake_request)

    with pytest.raises(ValueError, match="非公网地址"):
        safe_download_image("https://cdn.example.com/image.png")

    assert calls == ["https://cdn.example.com/image.png"]


def test_safe_download_image_allows_private_redirect_when_opted_in(monkeypatch):
    from backend.utils.remote_image import safe_download_image

    _patch_dns(monkeypatch, {
        "cdn.example.com": "93.184.216.34",
        "router.local": "192.168.1.1",
    })

    calls = []

    def fake_request(method, url, **kwargs):
        calls.append((url, kwargs.get("allow_private")))
        if url == "https://cdn.example.com/image.png":
            return _FakeImageResponse(status_code=302, headers={"Location": "http://router.local/private.png"})
        return _FakeImageResponse(chunks=[b"redirected-private-image"])

    monkeypatch.setattr("backend.utils.remote_image.safe_http_request", fake_request)

    assert safe_download_image("https://cdn.example.com/image.png", allow_private=True) == b"redirected-private-image"
    assert calls == [
        ("https://cdn.example.com/image.png", True),
        ("http://router.local/private.png", True),
    ]


def test_safe_download_image_enforces_streamed_size_limit(monkeypatch):
    from backend.utils.remote_image import safe_download_image

    _patch_dns(monkeypatch, {"cdn.example.com": "93.184.216.34"})
    monkeypatch.setenv("REDINK_REMOTE_IMAGE_MAX_BYTES", "4")

    def fake_request(method, url, **kwargs):
        return _FakeImageResponse(chunks=[b"abc", b"def"])

    monkeypatch.setattr("backend.utils.remote_image.safe_http_request", fake_request)

    with pytest.raises(ValueError, match="大小超过限制"):
        safe_download_image("https://cdn.example.com/image.png")


def test_safe_decode_base64_image_accepts_raw_and_data_url(monkeypatch):
    from backend.utils.remote_image import safe_decode_base64_image

    monkeypatch.setenv("REDINK_REMOTE_IMAGE_MAX_BYTES", "16")
    raw = base64.b64encode(b"image").decode("ascii")

    assert safe_decode_base64_image(raw) == b"image"
    assert safe_decode_base64_image(f"data:image/png;base64,{raw}") == b"image"


def test_safe_decode_base64_image_rejects_oversized_payload(monkeypatch):
    from backend.utils.remote_image import safe_decode_base64_image

    monkeypatch.setenv("REDINK_REMOTE_IMAGE_MAX_BYTES", "4")
    raw = base64.b64encode(b"too-large").decode("ascii")

    with pytest.raises(ValueError, match="超过大小限制"):
        safe_decode_base64_image(raw)


def test_safe_decode_base64_image_rejects_malformed_data_url(monkeypatch):
    from backend.utils.remote_image import safe_decode_base64_image

    monkeypatch.setenv("REDINK_REMOTE_IMAGE_MAX_BYTES", "16")

    with pytest.raises(ValueError, match="data URL 格式错误"):
        safe_decode_base64_image("data:image/png;base64")

    with pytest.raises(ValueError, match="必须使用 base64"):
        safe_decode_base64_image("data:image/png,not-base64")

    with pytest.raises(ValueError, match="格式错误"):
        safe_decode_base64_image("not valid base64")


def test_provider_probe_rejects_private_base_url_before_post(monkeypatch):
    from backend.routes import config_routes as cr

    _patch_dns(monkeypatch, {"metadata.internal": "169.254.169.254"})

    with pytest.raises(ValueError, match="非公网地址"):
        cr._test_openai_compatible(
            {
                "api_key": "sk-test",
                "base_url": "http://metadata.internal/v1",
                "model": "gpt-test",
            },
            "hello",
        )


def test_provider_model_probe_rejects_private_base_url_before_get(monkeypatch):
    from backend.routes import config_routes as cr

    _patch_dns(monkeypatch, {"router.local": "192.168.1.1"})

    with pytest.raises(ValueError, match="非公网地址"):
        cr._test_image_api(
            {
                "api_key": "sk-test",
                "base_url": "http://router.local/v1",
                "model": "image-test",
            }
        )


def test_admin_health_probe_rejects_private_base_url_before_get(monkeypatch):
    from backend.routes import admin_routes as ar

    _patch_dns(monkeypatch, {"localhost": "127.0.0.1"})

    result = ar._probe_openai_compatible_models("http://localhost:8317/v1", "sk-test")

    assert result["ok"] is False
    assert "非公网地址" in result["error"]


def test_provider_probe_private_url_opt_in_allows_loopback(monkeypatch):
    from backend.routes import admin_routes as ar

    _patch_dns(monkeypatch, {"localhost": "127.0.0.1"})
    monkeypatch.setenv("REDINK_ALLOW_PRIVATE_PROVIDER_URLS", "1")

    class DummyResponse:
        status_code = 200
        text = "OK"

    calls = []

    def fake_request(method, url, **kwargs):
        assert method == "GET"
        calls.append((url, kwargs))
        return DummyResponse()

    monkeypatch.setattr(ar, "safe_http_request", fake_request)

    result = ar._probe_openai_compatible_models("http://localhost:8317/v1", "sk-test")

    assert result["ok"] is True
    assert calls[0][0] == "http://localhost:8317/v1/models"
    assert calls[0][1]["allow_redirects"] is False


def test_provider_probe_private_url_opt_in_still_rejects_metadata(monkeypatch):
    from backend.routes import admin_routes as ar

    _patch_dns(monkeypatch, {"metadata.internal": "169.254.169.254"})
    monkeypatch.setenv("REDINK_ALLOW_PRIVATE_PROVIDER_URLS", "1")

    result = ar._probe_openai_compatible_models("http://metadata.internal/v1", "sk-test")

    assert result["ok"] is False
    assert "非公网地址" in result["error"]


def test_text_generation_client_rejects_private_base_url(monkeypatch):
    from backend.utils.text_client import TextChatClient

    _patch_dns(monkeypatch, {"localhost": "127.0.0.1"})

    with pytest.raises(ValueError, match="非公网地址"):
        TextChatClient(api_key="sk-test", base_url="http://localhost:8317/v1")


def test_text_generation_client_private_url_opt_in_disables_redirects(monkeypatch):
    from backend.utils.text_client import TextChatClient

    _patch_dns(monkeypatch, {"localhost": "127.0.0.1"})
    monkeypatch.setenv("REDINK_ALLOW_PRIVATE_PROVIDER_URLS", "1")

    class DummyResponse:
        status_code = 200
        text = ""

        def json(self):
            return {"choices": [{"message": {"content": "ok"}}]}

    calls = []

    def fake_request(method, url, **kwargs):
        assert method == "POST"
        calls.append((url, kwargs))
        return DummyResponse()

    monkeypatch.setattr("backend.utils.text_client.safe_http_request", fake_request)

    client = TextChatClient(api_key="sk-test", base_url="http://localhost:8317/v1")

    assert client.generate_text("hello") == "ok"
    assert calls[0][0] == "http://localhost:8317/v1/chat/completions"
    assert calls[0][1]["allow_redirects"] is False


def test_openai_image_generator_rejects_private_base_url(monkeypatch):
    from backend.generators.openai_compatible import OpenAICompatibleGenerator

    _patch_dns(monkeypatch, {"router.local": "192.168.1.1"})

    with pytest.raises(ValueError, match="非公网地址"):
        OpenAICompatibleGenerator(
            {
                "api_key": "sk-test",
                "base_url": "http://router.local/v1",
                "model": "image-test",
            }
        )


def test_image_api_generator_rejects_private_base_url(monkeypatch):
    from backend.generators.image_api import ImageApiGenerator

    _patch_dns(monkeypatch, {"router.local": "192.168.1.1"})

    with pytest.raises(ValueError, match="非公网地址"):
        ImageApiGenerator(
            {
                "api_key": "sk-test",
                "base_url": "http://router.local/v1",
                "model": "image-test",
            }
        )


def test_image_api_download_image_uses_safe_downloader_without_requests_nameerror(monkeypatch):
    from backend.generators.image_api import ImageApiGenerator

    generator = ImageApiGenerator({"api_key": "sk-test"})
    monkeypatch.setattr(
        "backend.generators.image_api.safe_download_image",
        lambda url, **kwargs: (_ for _ in ()).throw(TimeoutError("timed out")),
    )

    with pytest.raises(Exception, match="下载图片失败"):
        generator._download_image("https://cdn.example.com/image.png")


def test_openai_compatible_download_image_uses_safe_downloader_without_requests_nameerror(monkeypatch):
    from backend.generators.openai_compatible import OpenAICompatibleGenerator

    _patch_dns(monkeypatch, {"api.example.com": "93.184.216.34"})
    generator = OpenAICompatibleGenerator(
        {
            "api_key": "sk-test",
            "base_url": "https://api.example.com/v1",
            "model": "image-test",
        }
    )
    monkeypatch.setattr(
        "backend.generators.openai_compatible.safe_download_image",
        lambda url, **kwargs: (_ for _ in ()).throw(TimeoutError("timed out")),
    )

    with pytest.raises(Exception, match="下载图片失败"):
        generator._download_image("https://cdn.example.com/image.png")

