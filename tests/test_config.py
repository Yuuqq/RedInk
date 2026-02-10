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
