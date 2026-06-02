from backend.routes.utils import _safe_log_value


def test_safe_log_value_redacts_nested_secrets():
    value = _safe_log_value(
        "payload",
        {
            "api_key": "sk-secret",
            "nested": {
                "Authorization": "Bearer secret",
                "normal": "visible",
            },
            "items": [{"token": "secret-token"}],
        },
    )

    assert value["api_key"] == "[REDACTED]"
    assert value["nested"]["Authorization"] == "[REDACTED]"
    assert value["nested"]["normal"] == "visible"
    assert value["items"][0]["token"] == "[REDACTED]"
