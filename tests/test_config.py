"""
Tests for backend/config.py - Config class

Covers default values, environment-variable overrides, provider config
loading when YAML files are missing, and reload_config cache clearing.
"""

import os
import pytest


@pytest.fixture(autouse=True)
def reset_config():
    """Reset cached provider configs before and after each test."""
    from backend.config import Config

    Config._text_providers_config = None
    Config._image_providers_config = None
    yield
    Config._text_providers_config = None
    Config._image_providers_config = None


def _reload_config_class(monkeypatch_env=None):
    """
    Re-import the Config class so class-level attributes are re-evaluated
    with the current environment.

    Because Config.DEBUG, PORT, CORS_ORIGINS are set at class-definition
    time, we need to force a re-evaluation when env vars change.
    """
    import importlib
    import backend.config
    importlib.reload(backend.config)
    return backend.config.Config


# ---------- DEBUG ----------

class TestDebugFlag:
    def test_default_debug_is_false(self, monkeypatch):
        """DEBUG defaults to False when REDINK_DEBUG is not set."""
        monkeypatch.delenv("REDINK_DEBUG", raising=False)
        Config = _reload_config_class()

        assert Config.DEBUG is False

    def test_debug_from_env_true(self, monkeypatch):
        """Setting REDINK_DEBUG=true enables debug mode."""
        monkeypatch.setenv("REDINK_DEBUG", "true")
        Config = _reload_config_class()

        assert Config.DEBUG is True

    def test_debug_from_env_one(self, monkeypatch):
        """REDINK_DEBUG=1 is also treated as truthy."""
        monkeypatch.setenv("REDINK_DEBUG", "1")
        Config = _reload_config_class()

        assert Config.DEBUG is True

    def test_debug_from_env_false(self, monkeypatch):
        """REDINK_DEBUG=false keeps debug off."""
        monkeypatch.setenv("REDINK_DEBUG", "false")
        Config = _reload_config_class()

        assert Config.DEBUG is False


# ---------- PORT ----------

class TestPort:
    def test_default_port(self, monkeypatch):
        """Default port is 12398."""
        monkeypatch.delenv("REDINK_PORT", raising=False)
        Config = _reload_config_class()

        assert Config.PORT == 12398

    def test_port_from_env(self, monkeypatch):
        """REDINK_PORT overrides the default port."""
        monkeypatch.setenv("REDINK_PORT", "8080")
        Config = _reload_config_class()

        assert Config.PORT == 8080

    def test_invalid_port_env_falls_back_to_default(self, monkeypatch):
        """Invalid REDINK_PORT should not crash module import."""
        monkeypatch.setenv("REDINK_PORT", "not-a-port")
        Config = _reload_config_class()

        assert Config.PORT == 12398

    def test_out_of_range_port_env_falls_back_to_default(self, monkeypatch):
        """Out-of-range REDINK_PORT should not crash startup."""
        monkeypatch.setenv("REDINK_PORT", "70000")
        Config = _reload_config_class()

        assert Config.PORT == 12398


class TestHost:
    def test_default_host_is_loopback(self, monkeypatch):
        """Manual/local startup should not bind every interface by default."""
        monkeypatch.delenv("REDINK_HOST", raising=False)
        Config = _reload_config_class()

        assert Config.HOST == "127.0.0.1"

    def test_host_from_env(self, monkeypatch):
        monkeypatch.setenv("REDINK_HOST", "0.0.0.0")
        Config = _reload_config_class()

        assert Config.HOST == "0.0.0.0"


class TestNumericEnvLimits:
    def test_invalid_request_size_env_falls_back_to_default(self, monkeypatch):
        monkeypatch.setenv("REDINK_MAX_CONTENT_LENGTH", "bad")
        Config = _reload_config_class()

        assert Config.MAX_CONTENT_LENGTH == 32 * 1024 * 1024

    def test_negative_base64_limits_fall_back_to_default(self, monkeypatch):
        monkeypatch.setenv("REDINK_MAX_BASE64_IMAGES", "-1")
        monkeypatch.setenv("REDINK_MAX_BASE64_IMAGE_BYTES", "0")
        monkeypatch.setenv("REDINK_MAX_BASE64_TOTAL_BYTES", "0")
        Config = _reload_config_class()

        assert Config.MAX_BASE64_IMAGES == 8
        assert Config.MAX_BASE64_IMAGE_BYTES == 10 * 1024 * 1024
        assert Config.MAX_BASE64_TOTAL_BYTES == 24 * 1024 * 1024

    def test_invalid_history_zip_limit_falls_back_to_default(self, monkeypatch):
        monkeypatch.setenv("REDINK_MAX_HISTORY_ZIP_SOURCE_BYTES", "bad")
        Config = _reload_config_class()

        assert Config.MAX_HISTORY_ZIP_SOURCE_BYTES == 256 * 1024 * 1024


# ---------- CORS_ORIGINS ----------

class TestCorsOrigins:
    def test_cors_origins_default(self, monkeypatch):
        """Default CORS origins include localhost dev servers."""
        monkeypatch.delenv("REDINK_CORS_ORIGINS", raising=False)
        Config = _reload_config_class()

        assert "http://localhost:5173" in Config.CORS_ORIGINS
        assert "http://localhost:3000" in Config.CORS_ORIGINS

    def test_cors_origins_from_env(self, monkeypatch):
        """REDINK_CORS_ORIGINS overrides defaults with comma-separated list."""
        monkeypatch.setenv("REDINK_CORS_ORIGINS", "https://example.com,https://app.example.com")
        Config = _reload_config_class()

        assert Config.CORS_ORIGINS == ["https://example.com", "https://app.example.com"]

    def test_cors_origins_strips_whitespace(self, monkeypatch):
        """Whitespace around origins is stripped."""
        monkeypatch.setenv("REDINK_CORS_ORIGINS", " https://a.com , https://b.com ")
        Config = _reload_config_class()

        assert Config.CORS_ORIGINS == ["https://a.com", "https://b.com"]

    def test_get_cors_origins_reads_current_environment_without_reload(self, monkeypatch):
        from backend.config import Config

        monkeypatch.setenv("REDINK_CORS_ORIGINS", "https://runtime.example.com")

        assert Config.get_cors_origins() == ["https://runtime.example.com"]


# ---------- Provider config loading (missing files) ----------

class TestProviderConfigMissingFile:
    def test_load_text_providers_config_missing_file(self):
        """Returns default config when text_providers.yaml does not exist."""
        from backend.config import Config

        # The test environment likely does not have text_providers.yaml,
        # or the default is returned when file is missing.
        config = Config.load_text_providers_config()

        assert isinstance(config, dict)
        assert "active_provider" in config

    def test_load_image_providers_config_missing_file(self):
        """Returns default config when image_providers.yaml does not exist."""
        from backend.config import Config

        config = Config.load_image_providers_config()

        assert isinstance(config, dict)
        assert "active_provider" in config

    def test_provider_paths_can_be_overridden_by_env(self, monkeypatch, tmp_path):
        """Docker deployments can persist provider config outside the project root."""
        import yaml
        from backend.config import Config

        text_path = tmp_path / "text_providers.yaml"
        image_path = tmp_path / "image_providers.yaml"
        text_path.write_text(
            yaml.safe_dump({"active_provider": "txt", "providers": {"txt": {"type": "openai_compatible"}}}),
            encoding="utf-8",
        )
        image_path.write_text(
            yaml.safe_dump({"active_provider": "img", "providers": {"img": {"type": "image_api"}}}),
            encoding="utf-8",
        )

        monkeypatch.setenv("REDINK_TEXT_PROVIDERS_PATH", str(text_path))
        monkeypatch.setenv("REDINK_IMAGE_PROVIDERS_PATH", str(image_path))
        Config.reload_config()

        assert Config.get_text_providers_path() == text_path
        assert Config.get_image_providers_path() == image_path
        assert Config.load_text_providers_config()["active_provider"] == "txt"
        assert Config.load_image_providers_config()["active_provider"] == "img"

    def test_provider_paths_must_be_distinct(self, monkeypatch, tmp_path):
        """Text/image provider config paths must not point at the same file."""
        from backend.config import Config

        shared_path = tmp_path / "providers.yaml"
        monkeypatch.setenv("REDINK_TEXT_PROVIDERS_PATH", str(shared_path))
        monkeypatch.setenv("REDINK_IMAGE_PROVIDERS_PATH", str(shared_path))

        with pytest.raises(ValueError, match="不能指向同一个文件"):
            Config.validate_provider_config_paths()


class TestProviderConfigShape:
    def test_rejects_non_mapping_provider_config(self):
        from backend.config import Config

        with pytest.raises(ValueError, match="顶层必须是对象"):
            Config._validate_provider_config_shape(["bad"], "text_providers.yaml")

    def test_rejects_non_mapping_providers(self):
        from backend.config import Config

        with pytest.raises(ValueError, match="providers 必须是对象"):
            Config._validate_provider_config_shape(
                {"active_provider": "default", "providers": ["bad"]},
                "text_providers.yaml",
            )

    def test_rejects_invalid_provider_entry_shape(self):
        from backend.config import Config

        with pytest.raises(ValueError, match="服务商配置必须是对象"):
            Config._validate_provider_config_shape(
                {"active_provider": "default", "providers": {"default": ["bad"]}},
                "text_providers.yaml",
            )

    def test_selects_provider_when_active_provider_empty(self):
        from backend.config import Config

        config = Config._validate_provider_config_shape(
            {"active_provider": "", "providers": {"default": {}}},
            "text_providers.yaml",
        )

        assert config["active_provider"] == "default"

    def test_rejects_active_provider_missing_from_providers(self):
        from backend.config import Config

        with pytest.raises(ValueError, match="active_provider 不存在于 providers"):
            Config._validate_provider_config_shape(
                {"active_provider": "missing", "providers": {"default": {}}},
                "text_providers.yaml",
            )

    def test_allows_active_provider_when_providers_empty(self):
        from backend.config import Config

        config = Config._validate_provider_config_shape(
            {"active_provider": "default", "providers": {}},
            "text_providers.yaml",
        )

        assert config["active_provider"] == "default"

    def test_rejects_unsupported_provider_type_when_allowlist_is_set(self):
        from backend.config import Config

        with pytest.raises(ValueError, match="服务商类型不支持"):
            Config._validate_provider_config_shape(
                {"active_provider": "default", "providers": {"default": {"type": "image_api"}}},
                "text_providers.yaml",
                allowed_types={"google_gemini", "openai_compatible"},
            )

    def test_accepts_supported_provider_type_when_allowlist_is_set(self):
        from backend.config import Config

        config = Config._validate_provider_config_shape(
            {"active_provider": "default", "providers": {"default": {"type": " openai_compatible "}}},
            "text_providers.yaml",
            allowed_types={"google_gemini", "openai_compatible"},
        )

        assert config["providers"]["default"]["type"] == "openai_compatible"

    def test_rejects_missing_type_when_provider_name_is_not_supported(self):
        from backend.config import Config

        with pytest.raises(ValueError, match="服务商类型不支持"):
            Config._validate_provider_config_shape(
                {"active_provider": "default", "providers": {"default": {}}},
                "text_providers.yaml",
                allowed_types={"google_gemini", "openai_compatible"},
            )

    def test_allows_missing_type_when_provider_name_is_supported(self):
        from backend.config import Config

        config = Config._validate_provider_config_shape(
            {"active_provider": "openai_compatible", "providers": {"openai_compatible": {}}},
            "text_providers.yaml",
            allowed_types={"google_gemini", "openai_compatible"},
        )

        assert "openai_compatible" in config["providers"]

    def test_rejects_invalid_base_url_when_loading_manual_yaml(self):
        from backend.config import Config

        with pytest.raises(ValueError, match="base_url 不允许包含用户名或密码"):
            Config._validate_provider_config_shape(
                {
                    "active_provider": "default",
                    "providers": {
                        "default": {
                            "type": "openai_compatible",
                            "base_url": "https://user:pass@example.com/v1",
                        }
                    },
                },
                "text_providers.yaml",
                allowed_types={"google_gemini", "openai_compatible"},
            )

    def test_normalizes_endpoint_path_when_loading_manual_yaml(self):
        from backend.config import Config

        config = Config._validate_provider_config_shape(
            {
                "active_provider": "default",
                "providers": {
                    "default": {
                        "type": "openai_compatible",
                        "endpoint_type": "v1/chat/completions",
                    }
                },
            },
            "text_providers.yaml",
            allowed_types={"google_gemini", "openai_compatible"},
        )

        assert config["providers"]["default"]["endpoint_type"] == "/v1/chat/completions"

    def test_rejects_full_url_endpoint_when_loading_manual_yaml(self):
        from backend.config import Config

        with pytest.raises(ValueError, match="endpoint_type 必须是 URL path"):
            Config._validate_provider_config_shape(
                {
                    "active_provider": "default",
                    "providers": {
                        "default": {
                            "type": "openai_compatible",
                            "endpoint_type": "https://evil.example/v1/chat/completions",
                        }
                    },
                },
                "text_providers.yaml",
                allowed_types={"google_gemini", "openai_compatible"},
            )


# ---------- reload_config ----------

class TestReloadConfig:
    def test_reload_config(self):
        """reload_config clears cached provider configs."""
        from backend.config import Config

        # Populate caches
        Config.load_text_providers_config()
        Config.load_image_providers_config()

        assert Config._text_providers_config is not None
        assert Config._image_providers_config is not None

        # Reload should clear both
        Config.reload_config()

        assert Config._text_providers_config is None
        assert Config._image_providers_config is None
