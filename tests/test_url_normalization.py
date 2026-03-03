from backend.utils.url import normalize_openai_base_url


def test_normalize_openai_base_url_strips_trailing_v1():
    assert normalize_openai_base_url("https://example.com/v1") == "https://example.com"
    assert normalize_openai_base_url("https://example.com/v1/") == "https://example.com"
    assert normalize_openai_base_url("https://example.com////v1////") == "https://example.com"


def test_normalize_openai_base_url_does_not_corrupt_v11():
    assert normalize_openai_base_url("https://example.com/v11") == "https://example.com/v11"
    assert normalize_openai_base_url("https://example.com/v11/") == "https://example.com/v11"


def test_normalize_openai_base_url_handles_defaults_and_whitespace():
    assert normalize_openai_base_url(None, default="https://api.openai.com/v1") == "https://api.openai.com"
    assert normalize_openai_base_url("   ", default="https://api.openai.com") == "https://api.openai.com"
    assert normalize_openai_base_url("   ") == ""

