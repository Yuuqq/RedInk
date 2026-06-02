"""
Tests for request validation on JSON endpoints.

These endpoints should not crash (500) on malformed/non-object JSON bodies.
"""

import pytest


@pytest.mark.parametrize(
    "method,path",
    [
        ("POST", "/api/content"),
        ("POST", "/api/outline"),
        ("POST", "/api/generate"),
        ("POST", "/api/history"),
        ("PUT", "/api/history/test-record"),
        ("POST", "/api/config"),
        ("POST", "/api/config/test"),
        ("POST", "/api/retry"),
        ("POST", "/api/retry-failed"),
        ("POST", "/api/regenerate"),
        ("POST", "/api/admin/history/cleanup"),
    ],
)
def test_rejects_non_object_json(client, method, path):
    """
    Sending a JSON array should return 400 with a JSON error response.

    Historically, several routes assumed request.get_json() returned a dict and
    crashed with AttributeError when it returned a list/None.
    """
    fn = getattr(client, method.lower())
    resp = fn(path, data="[]", content_type="application/json")

    assert resp.status_code == 400
    data = resp.get_json()
    assert isinstance(data, dict)
    assert data.get("success") is False


@pytest.mark.parametrize(
    "method,path",
    [
        ("POST", "/api/content"),
        ("POST", "/api/outline"),
        ("POST", "/api/generate"),
        ("POST", "/api/history"),
        ("PUT", "/api/history/test-record"),
        ("POST", "/api/config"),
    ],
)
def test_rejects_malformed_json(client, method, path):
    """Malformed JSON should return 400 and not a 500."""
    fn = getattr(client, method.lower())
    resp = fn(path, data="{bad json", content_type="application/json")

    assert resp.status_code == 400
    data = resp.get_json()
    assert isinstance(data, dict)
    assert data.get("success") is False


def test_outline_rejects_non_string_topic(client):
    resp = client.post("/api/outline", json={"topic": 123})

    assert resp.status_code == 400
    data = resp.get_json()
    assert isinstance(data, dict)
    assert data.get("success") is False
    assert "topic 必须是字符串" in data.get("error", "")


@pytest.mark.parametrize(
    "path,payload,expected_error",
    [
        (
            "/api/generate",
            {"pages": [{"index": 0, "type": "cover", "content": "ok"}, "bad-page"]},
            "page 必须是 JSON object",
        ),
        (
            "/api/generate",
            {"pages": [{"index": -1, "type": "cover", "content": "ok"}]},
            "page.index 必须是非负整数",
        ),
        (
            "/api/generate",
            {"pages": [{"index": 0, "type": 123, "content": "ok"}]},
            "page.type 必须是字符串",
        ),
        (
            "/api/generate",
            {"pages": [{"index": 0, "type": "cover", "content": 123}]},
            "page.content 必须是字符串",
        ),
        (
            "/api/generate",
            {
                "pages": [{"index": 0, "type": "cover", "content": "ok"}],
                "full_outline": 123,
            },
            "full_outline 必须是字符串",
        ),
        (
            "/api/generate",
            {
                "pages": [{"index": 0, "type": "cover", "content": "ok"}],
                "user_topic": 123,
            },
            "user_topic 必须是字符串",
        ),
        (
            "/api/generate",
            {
                "pages": [{"index": 0, "type": "cover", "content": "ok"}],
                "style_hint": 123,
            },
            "style_hint 必须是字符串",
        ),
        (
            "/api/generate",
            {
                "pages": [
                    {"index": 0, "type": "cover", "content": "ok"},
                    {"index": 0, "type": "content", "content": "dup"},
                ]
            },
            "pages 中的 index 不能重复",
        ),
        (
            "/api/generate",
            {
                "pages": [
                    {"index": 0, "type": "cover", "content": "ok"},
                    {"index": 2, "type": "content", "content": "gap"},
                ]
            },
            "pages.index 必须从 0 开始连续",
        ),
        (
            "/api/retry-failed",
            {
                "task_id": "task_12345678",
                "pages": [{"index": 0, "type": "cover", "content": "ok"}, {"index": 0, "type": "content", "content": "dup"}],
            },
            "pages 中的 index 不能重复",
        ),
        (
            "/api/retry-failed",
            {
                "task_id": "task_12345678",
                "pages": [{"index": 0, "type": "cover", "content": "ok"}, {"index": 2, "type": "content", "content": "gap"}],
            },
            "pages.index 必须从 0 开始连续",
        ),
        (
            "/api/retry",
            {"task_id": "task_12345678", "page": {"index": -1, "type": "cover", "content": "ok"}},
            "page.index 必须是非负整数",
        ),
        (
            "/api/retry",
            {"task_id": "task_12345678", "page": {"index": 0, "type": 123, "content": "ok"}},
            "page.type 必须是字符串",
        ),
        (
            "/api/retry",
            {"task_id": "task_12345678", "page": {"index": 0, "type": "cover", "content": 123}},
            "page.content 必须是字符串",
        ),
        (
            "/api/regenerate",
            {"task_id": "task_12345678", "page": {"index": -1, "type": "cover", "content": "ok"}},
            "page.index 必须是非负整数",
        ),
        (
            "/api/regenerate",
            {"task_id": "task_12345678", "page": {"index": 0, "type": 123, "content": "ok"}},
            "page.type 必须是字符串",
        ),
        (
            "/api/regenerate",
            {"task_id": "task_12345678", "page": {"index": 0, "type": "cover", "content": 123}},
            "page.content 必须是字符串",
        ),
    ],
)
def test_image_routes_reject_invalid_page_structures(client, path, payload, expected_error):
    resp = client.post(path, json=payload)

    assert resp.status_code == 400
    data = resp.get_json()
    assert isinstance(data, dict)
    assert data.get("success") is False
    assert expected_error in data.get("error", "")


@pytest.mark.parametrize(
    "method,path",
    [
        ("GET", "/api/task/bad!"),
        ("POST", "/api/task/bad!/cancel"),
    ],
)
def test_task_routes_reject_unsafe_task_id(client, method, path):
    fn = getattr(client, method.lower())
    resp = fn(path)

    assert resp.status_code == 400
    data = resp.get_json()
    assert isinstance(data, dict)
    assert data.get("success") is False
    assert "task_id 不安全" in data.get("error", "")

