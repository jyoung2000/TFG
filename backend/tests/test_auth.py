"""Tests for shared-secret authentication middleware."""

from __future__ import annotations

import base64

from starlette.testclient import TestClient

from app_factory import create_app


def test_request_without_token_returns_401(test_state):
    app = create_app(handler=test_state, auth_token="test-secret")
    with TestClient(app) as client:
        response = client.get("/health")
        assert response.status_code == 401
        assert response.json() == {"error": "Unauthorized"}


def test_request_with_correct_bearer_token(test_state):
    app = create_app(handler=test_state, auth_token="test-secret")
    with TestClient(app) as client:
        response = client.get("/health", headers={"Authorization": "Bearer test-secret"})
        assert response.status_code == 200


def test_request_with_correct_basic_auth(test_state):
    app = create_app(handler=test_state, auth_token="test-secret")
    credentials = base64.b64encode(b":test-secret").decode()
    with TestClient(app) as client:
        response = client.get("/health", headers={"Authorization": f"Basic {credentials}"})
        assert response.status_code == 200


def test_request_with_wrong_token_returns_401(test_state):
    app = create_app(handler=test_state, auth_token="test-secret")
    with TestClient(app) as client:
        response = client.get("/health", headers={"Authorization": "Bearer wrong-token"})
        assert response.status_code == 401


def test_health_without_token_returns_401(test_state):
    """Health endpoint is NOT exempt from auth."""
    app = create_app(handler=test_state, auth_token="test-secret")
    with TestClient(app) as client:
        response = client.get("/health")
        assert response.status_code == 401


def test_no_auth_token_disables_middleware(test_state):
    """When auth_token is empty string, auth is disabled (dev/test mode)."""
    app = create_app(handler=test_state, auth_token="")
    with TestClient(app) as client:
        response = client.get("/health")
        assert response.status_code == 200


def test_websocket_with_token_query_param(test_state):
    app = create_app(handler=test_state, auth_token="test-secret")
    with TestClient(app) as client:
        # WebSocket upgrade without token should fail with 401
        response = client.get(
            "/ws/download/test",
            headers={"upgrade": "websocket", "connection": "upgrade"},
        )
        assert response.status_code == 401

        # WebSocket upgrade with correct token query param
        response = client.get(
            "/ws/download/test?token=test-secret",
            headers={"upgrade": "websocket", "connection": "upgrade"},
        )
        # The route may not exist, but auth should pass (not 401)
        assert response.status_code != 401


class TestMediaQueryToken:
    """Film media GETs are loaded via <img>/<video> tags, which cannot send an
    Authorization header — they accept the shared token as a query param."""

    def test_media_get_accepts_query_token(self, test_state):
        app = create_app(handler=test_state, auth_token="test-secret")
        with TestClient(app) as client:
            response = client.get(
                "/api/film/projects/p1/media",
                params={"path": "captures/none.png", "token": "test-secret"},
            )
            # Authenticated (404 = passed auth, media simply doesn't exist).
            assert response.status_code == 404

    def test_media_get_rejects_wrong_query_token(self, test_state):
        app = create_app(handler=test_state, auth_token="test-secret")
        with TestClient(app) as client:
            response = client.get(
                "/api/film/projects/p1/media",
                params={"path": "captures/none.png", "token": "wrong"},
            )
            assert response.status_code == 401

    def test_query_token_not_accepted_on_other_routes(self, test_state):
        app = create_app(handler=test_state, auth_token="test-secret")
        with TestClient(app) as client:
            response = client.get("/api/film/queue", params={"token": "test-secret"})
            assert response.status_code == 401

    def test_output_route_accepts_query_token(self, test_state):
        app = create_app(handler=test_state, auth_token="test-secret")
        with TestClient(app) as client:
            response = client.get(
                "/api/film/output",
                params={"path": str(test_state.config.outputs_dir / "missing.mp4"), "token": "test-secret"},
            )
            assert response.status_code == 404


def test_a_media_element_can_load_a_library_preview_with_a_query_token(test_state):
    """A <video> cannot send an Authorization header, so these GETs take a token.

    The allowance is deliberately narrow: read-only GETs that serve one file
    the backend resolved itself, never a path the caller supplied.
    """
    app = create_app(handler=test_state, auth_token="test-secret")
    with TestClient(app) as client:
        unauthenticated = client.get("/api/shot-library/lib-nope/preview")
        assert unauthenticated.status_code == 401
        # With the token the request is authorised; the item still does not
        # exist, which is a 404 — and that is the point: it got past auth.
        authorised = client.get("/api/shot-library/lib-nope/preview?token=test-secret")
        assert authorised.status_code == 404


def test_the_query_token_allowance_does_not_extend_to_the_rest_of_the_library(test_state):
    """Only the preview. Listing, editing and deleting still need a header."""
    app = create_app(handler=test_state, auth_token="test-secret")
    with TestClient(app) as client:
        assert client.get("/api/shot-library?token=test-secret").status_code == 401
        assert client.delete("/api/shot-library/lib-nope?token=test-secret").status_code == 401
