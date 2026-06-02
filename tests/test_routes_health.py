"""
Tests for API health and root endpoints.

Uses the Flask test client fixture from conftest.py.
"""

import os
import logging
from pathlib import Path

import pytest
import yaml


class TestHealthEndpoint:
    def test_health_endpoint(self, client):
        """GET /api/health returns 200 with a success field."""
        response = client.get("/api/health")

        assert response.status_code == 200

        data = response.get_json()
        assert data is not None
        assert data["success"] is True

    def test_health_endpoint_returns_json(self, client):
        """Health endpoint content type is JSON."""
        response = client.get("/api/health")

        assert response.content_type.startswith("application/json")


class TestNetworkExposureGuard:
    def test_all_interfaces_requires_auth_token(self, monkeypatch):
        from backend.app import _validate_network_exposure_config

        monkeypatch.delenv("REDINK_AUTH_TOKEN", raising=False)
        monkeypatch.delenv("REDINK_ALLOW_UNAUTH_REMOTE", raising=False)

        with pytest.raises(RuntimeError, match="REDINK_AUTH_TOKEN"):
            _validate_network_exposure_config("0.0.0.0")

    def test_all_interfaces_allowed_with_auth_token(self, monkeypatch):
        from backend.app import _validate_network_exposure_config

        monkeypatch.setenv("REDINK_AUTH_TOKEN", "secret")
        monkeypatch.delenv("REDINK_ALLOW_UNAUTH_REMOTE", raising=False)

        _validate_network_exposure_config("0.0.0.0")

    def test_loopback_requires_auth_token_without_explicit_unsafe_opt_in(self, monkeypatch):
        from backend.app import _validate_network_exposure_config

        monkeypatch.delenv("REDINK_AUTH_TOKEN", raising=False)
        monkeypatch.delenv("REDINK_ALLOW_UNAUTH_REMOTE", raising=False)

        with pytest.raises(RuntimeError, match="REDINK_AUTH_TOKEN"):
            _validate_network_exposure_config("127.0.0.1")

    def test_unauthenticated_start_allowed_with_explicit_unsafe_opt_in(self, monkeypatch):
        from backend.app import _validate_network_exposure_config

        monkeypatch.delenv("REDINK_AUTH_TOKEN", raising=False)
        monkeypatch.setenv("REDINK_ALLOW_UNAUTH_REMOTE", "1")

        _validate_network_exposure_config("127.0.0.1")

    def test_loopback_request_rejected_without_auth_token(self, client, monkeypatch):
        monkeypatch.delenv("REDINK_AUTH_TOKEN", raising=False)
        monkeypatch.delenv("REDINK_ALLOW_UNAUTH_REMOTE", raising=False)

        response = client.get("/api/health", environ_base={"REMOTE_ADDR": "127.0.0.1"})

        assert response.status_code == 403
        assert "REDINK_AUTH_TOKEN" in response.get_json()["error"]

    def test_remote_request_rejected_without_auth_token(self, client, monkeypatch):
        monkeypatch.delenv("REDINK_AUTH_TOKEN", raising=False)
        monkeypatch.delenv("REDINK_ALLOW_UNAUTH_REMOTE", raising=False)

        response = client.get("/api/health", environ_base={"REMOTE_ADDR": "203.0.113.10"})

        assert response.status_code == 403
        assert "REDINK_AUTH_TOKEN" in response.get_json()["error"]

    def test_remote_request_allowed_with_auth_token(self, client, monkeypatch):
        monkeypatch.setenv("REDINK_AUTH_TOKEN", "secret")
        monkeypatch.delenv("REDINK_ALLOW_UNAUTH_REMOTE", raising=False)

        response = client.get("/api/health", environ_base={"REMOTE_ADDR": "203.0.113.10"})

        assert response.status_code == 200

    def test_cors_preflight_allows_authorization_when_auth_token_enabled(self, client, monkeypatch):
        monkeypatch.setenv("REDINK_AUTH_TOKEN", "secret")

        response = client.options(
            "/api/config",
            headers={
                "Origin": "http://localhost:5173",
                "Access-Control-Request-Method": "GET",
                "Access-Control-Request-Headers": "Authorization",
            },
        )

        assert response.status_code == 200
        assert response.headers.get("Access-Control-Allow-Origin") == "http://localhost:5173"
        assert "Authorization" in response.headers.get("Access-Control-Allow-Headers", "")

    def test_cors_preflight_still_fails_closed_without_auth_configuration(self, client, monkeypatch):
        monkeypatch.delenv("REDINK_AUTH_TOKEN", raising=False)
        monkeypatch.delenv("REDINK_ALLOW_UNAUTH_REMOTE", raising=False)

        response = client.options(
            "/api/config",
            headers={
                "Origin": "http://localhost:5173",
                "Access-Control-Request-Method": "GET",
                "Access-Control-Request-Headers": "Authorization",
            },
        )

        assert response.status_code == 403
        assert "REDINK_AUTH_TOKEN" in response.get_json()["error"]


class TestStartupConfigValidation:
    def test_startup_rejects_invalid_provider_config(self, monkeypatch, tmp_path):
        from backend.app import create_app
        from backend.config import Config

        text_path = tmp_path / "text_providers.yaml"
        image_path = tmp_path / "image_providers.yaml"
        text_path.write_text(
            "active_provider: missing\nproviders:\n  default:\n    type: openai_compatible\n",
            encoding="utf-8",
        )
        image_path.write_text("active_provider: default\nproviders: {}\n", encoding="utf-8")

        monkeypatch.setenv("REDINK_AUTH_TOKEN", "secret")
        monkeypatch.setenv("REDINK_TEXT_PROVIDERS_PATH", str(text_path))
        monkeypatch.setenv("REDINK_IMAGE_PROVIDERS_PATH", str(image_path))
        Config.reload_config()

        with pytest.raises(ValueError, match="active_provider 不存在于 providers"):
            create_app()

        Config.reload_config()


class TestLoggingSetup:
    def test_safe_rotating_file_handler_falls_back_to_copy_truncate(self, tmp_path, monkeypatch):
        from logging.handlers import RotatingFileHandler
        from backend.app import SafeRotatingFileHandler

        log_file = tmp_path / "redink.log"
        log_file.write_text("old log\n", encoding="utf-8")

        def fail_rollover(_self):
            raise PermissionError("locked")

        monkeypatch.setattr(RotatingFileHandler, "doRollover", fail_rollover)

        handler = SafeRotatingFileHandler(
            str(log_file),
            maxBytes=1024,
            backupCount=1,
            encoding="utf-8",
        )
        try:
            handler.doRollover()
            handler.emit(logging.LogRecord(
                name="test",
                level=logging.INFO,
                pathname=__file__,
                lineno=1,
                msg="new log",
                args=(),
                exc_info=None,
            ))
        finally:
            handler.close()

        assert log_file.read_text(encoding="utf-8").endswith("new log\n")
        backups = list(tmp_path.glob("redink.log.*.bak"))
        assert backups
        assert backups[0].read_text(encoding="utf-8") == "old log\n"

    def test_setup_logging_closes_existing_handlers(self, tmp_path, monkeypatch):
        from backend.app import setup_logging

        old_log = tmp_path / "old.log"
        new_log = tmp_path / "new.log"
        old_handler = logging.FileHandler(old_log, encoding="utf-8")
        root_logger = logging.getLogger()
        root_logger.addHandler(old_handler)

        monkeypatch.setenv("REDINK_LOG_FILE", str(new_log))

        try:
            setup_logging()

            assert old_handler.stream is None
        finally:
            for handler in list(root_logger.handlers):
                root_logger.removeHandler(handler)
                handler.close()


class TestRootEndpoint:
    def test_root_returns_200(self, client):
        """GET / returns 200 regardless of dev or static-hosting mode."""
        response = client.get("/")

        assert response.status_code == 200

    def test_root_returns_json_in_dev_mode(self, client):
        """GET / returns JSON with API info when frontend/dist is absent.

        If frontend/dist exists (static hosting mode), the root serves HTML
        instead, so this test is skipped in that environment.
        """
        frontend_dist = Path(__file__).parent.parent / "frontend" / "dist"
        if frontend_dist.exists():
            pytest.skip("frontend/dist exists; app serves HTML in static mode")

        response = client.get("/")
        data = response.get_json()

        assert data is not None
        assert "message" in data

    def test_static_mode_missing_assets_do_not_fallback_to_index(self, client):
        """Missing static assets should 404 instead of returning index.html."""
        frontend_dist = Path(__file__).parent.parent / "frontend" / "dist"
        if not frontend_dist.exists():
            pytest.skip("frontend/dist absent; app is in API-only dev mode")

        response = client.get("/assets/missing-file.js")

        assert response.status_code == 404
        assert not response.content_type.startswith("text/html")

    def test_static_mode_frontend_routes_still_fallback_to_index(self, client):
        """Vue history-mode routes should still return the SPA shell."""
        frontend_dist = Path(__file__).parent.parent / "frontend" / "dist"
        if not frontend_dist.exists():
            pytest.skip("frontend/dist absent; app is in API-only dev mode")

        response = client.get("/history/some-record-id")

        assert response.status_code == 200
        assert response.content_type.startswith("text/html")


class TestDockerComposeDeploymentConfig:
    def test_compose_forwards_documented_runtime_envs(self):
        compose_path = Path(__file__).parent.parent / "docker-compose.yml"
        compose = yaml.safe_load(compose_path.read_text(encoding="utf-8"))
        env_entries = compose["services"]["csslab"]["environment"]
        env_names = {entry.split("=", 1)[0] for entry in env_entries}

        expected = {
            "REDINK_AUTH_TOKEN",
            "REDINK_RATE_LIMIT",
            "REDINK_RATE_LIMIT_STORAGE_URI",
            "REDINK_PORT",
            "REDINK_GUNICORN_WORKERS",
            "REDINK_GUNICORN_THREADS",
            "REDINK_GUNICORN_TIMEOUT",
            "REDINK_ALLOW_PRIVATE_PROVIDER_URLS",
            "REDINK_ALLOW_UNPINNED_PROVIDER_URLS",
            "REDINK_MAX_CONTENT_LENGTH",
            "REDINK_MAX_BASE64_IMAGES",
            "REDINK_MAX_BASE64_IMAGE_BYTES",
            "REDINK_MAX_BASE64_TOTAL_BYTES",
            "REDINK_MAX_HISTORY_ZIP_SOURCE_BYTES",
            "REDINK_REMOTE_IMAGE_MAX_BYTES",
            "REDINK_TASK_STATE_TTL_SECONDS",
            "REDINK_TEXT_PROVIDERS_PATH",
            "REDINK_IMAGE_PROVIDERS_PATH",
        }

        assert expected <= env_names

        ports = compose["services"]["csslab"]["ports"]
        assert "${REDINK_PORT:-12398}:${REDINK_PORT:-12398}" in ports

    def test_compose_persists_actual_image_storage_directory(self):
        compose_path = Path(__file__).parent.parent / "docker-compose.yml"
        compose = yaml.safe_load(compose_path.read_text(encoding="utf-8"))
        volumes = set(compose["services"]["csslab"]["volumes"])

        assert "./history:/app/history" in volumes
        assert "./config:/app/config" in volumes
        assert "./output:/app/output" not in volumes

    def test_dockerignore_excludes_local_temp_directories(self):
        dockerignore = (Path(__file__).parent.parent / ".dockerignore").read_text(encoding="utf-8").splitlines()
        entries = {line.strip() for line in dockerignore if line.strip() and not line.startswith("#")}

        assert ".tmp" in entries
        assert "*.tmp" in entries

    def test_dockerfile_healthcheck_uses_runtime_port(self):
        dockerfile = (Path(__file__).parent.parent / "Dockerfile").read_text(encoding="utf-8")

        assert "os.environ.get('REDINK_PORT', '12398')" in dockerfile
        assert "localhost:12398/api/health" not in dockerfile

    def test_dockerfile_seeds_persistent_provider_config(self):
        dockerfile = (Path(__file__).parent.parent / "Dockerfile").read_text(encoding="utf-8")
        entrypoint = (Path(__file__).parent.parent / "docker" / "docker-entrypoint.sh").read_text(encoding="utf-8")

        assert "COPY docker/text_providers.yaml ./default-config/text_providers.yaml" in dockerfile
        assert "COPY docker/image_providers.yaml ./default-config/image_providers.yaml" in dockerfile
        assert 'ENTRYPOINT ["/app/docker-entrypoint.sh"]' in dockerfile
        assert "REDINK_TEXT_PROVIDERS_PATH=/app/config/text_providers.yaml" in dockerfile
        assert "REDINK_IMAGE_PROVIDERS_PATH=/app/config/image_providers.yaml" in dockerfile
        assert "[ ! -e \"$dest\" ]" in entrypoint
        assert "seed_config /app/default-config/text_providers.yaml" in entrypoint
        assert "seed_config /app/default-config/image_providers.yaml" in entrypoint

    def test_vite_dev_proxy_uses_configurable_backend_port(self):
        vite_config = (Path(__file__).parent.parent / "frontend" / "vite.config.ts").read_text(encoding="utf-8")

        assert "VITE_API_PROXY_TARGET" in vite_config
        assert "env.REDINK_PORT || '12398'" in vite_config
        assert "target: 'http://localhost:12398'" not in vite_config
