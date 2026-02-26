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

