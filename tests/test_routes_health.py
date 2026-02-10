"""
Tests for API health and root endpoints.

Uses the Flask test client fixture from conftest.py.
"""

import os
from pathlib import Path

import pytest


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
