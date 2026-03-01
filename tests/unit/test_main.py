"""Unit tests for app/main.py — exception handlers, middleware, routes, health check."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import Request
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.exceptions import (
    AgentError,
    LLMProviderError,
    OrchestratorError,
    ServiceUnavailableError,
    ValidationError,
)
from app.db.database import init_db
from app.main import (
    ApiVersionHeadersMiddleware,
    RequestLoggingMiddleware,
    SecurityHeadersMiddleware,
    _DEPRECATED_PREFIXES,
    _check_database_liveness,
    agent_exception_handler,
    app,
    general_exception_handler,
    llm_provider_exception_handler,
    orchestrator_exception_handler,
    service_unavailable_exception_handler,
    validation_exception_handler,
)


# ---------------------------------------------------------------------------
# Module-level DB patch (prevents "unable to open database file" on Windows)
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True, scope="module")
def use_in_memory_db():
    """Redirect all DB calls to an in-memory SQLite DB for this test module."""
    import app.core.persistence as persistence_module
    import app.core.run_store as run_store_module
    import app.db.database as db_module

    original_engine = db_module.engine
    original_session = db_module.SessionLocal
    original_run_store_session = run_store_module.SessionLocal
    original_persistence_session = persistence_module.SessionLocal

    new_engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    new_session_factory = sessionmaker(autocommit=False, autoflush=False, bind=new_engine)

    db_module.engine = new_engine
    db_module.SessionLocal = new_session_factory
    run_store_module.SessionLocal = new_session_factory
    persistence_module.SessionLocal = new_session_factory

    init_db()
    yield

    db_module.engine = original_engine
    db_module.SessionLocal = original_session
    run_store_module.SessionLocal = original_run_store_session
    persistence_module.SessionLocal = original_persistence_session


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_mock_request(request_id: str = "test-req-id") -> MagicMock:
    """Create a mock FastAPI Request with a state.request_id."""
    mock_req = MagicMock(spec=Request)
    mock_req.state = MagicMock()
    mock_req.state.request_id = request_id
    return mock_req


def _make_healthy_container():
    """Return a mock ServiceContainer that passes all health checks."""
    container = MagicMock()
    mock_registry = MagicMock()
    mock_registry.get_all.return_value = [MagicMock()]
    container.get_agent_registry.return_value = mock_registry
    mock_llm = MagicMock()
    mock_llm.get_provider.return_value = MagicMock()
    container.get_llm_manager.return_value = mock_llm
    return container


# ---------------------------------------------------------------------------
# Exception handlers (lines 211-338)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestExceptionHandlers:
    """Call each @app.exception_handler directly to cover their bodies."""

    @pytest.mark.asyncio
    async def test_orchestrator_exception_handler_returns_500(self):
        """Covers lines 211-228: OrchestratorError → 500 JSON response."""
        req = _make_mock_request()
        exc = OrchestratorError("orch failed", error_code="ORCH_ERR")
        response = await orchestrator_exception_handler(req, exc)
        assert response.status_code == 500
        body = json.loads(response.body)
        assert body["error"]["code"] == "ORCH_ERR"

    @pytest.mark.asyncio
    async def test_agent_exception_handler_returns_500(self):
        """Covers lines 234-252: AgentError → 500 JSON response."""
        req = _make_mock_request()
        exc = AgentError("agent failed", agent_id="diag-agent")
        response = await agent_exception_handler(req, exc)
        assert response.status_code == 500
        body = json.loads(response.body)
        assert body["error"]["agent_id"] == "diag-agent"

    @pytest.mark.asyncio
    async def test_llm_provider_exception_handler_returns_503(self):
        """Covers lines 258-276: LLMProviderError → 503 JSON response."""
        req = _make_mock_request()
        exc = LLMProviderError("llm down", provider="bedrock")
        response = await llm_provider_exception_handler(req, exc)
        assert response.status_code == 503
        body = json.loads(response.body)
        assert body["error"]["provider"] == "bedrock"

    @pytest.mark.asyncio
    async def test_validation_exception_handler_returns_400(self):
        """Covers lines 282-299: ValidationError → 400 JSON response."""
        req = _make_mock_request()
        exc = ValidationError("bad field", field="goal")
        response = await validation_exception_handler(req, exc)
        assert response.status_code == 400
        body = json.loads(response.body)
        assert body["error"]["field"] == "goal"

    @pytest.mark.asyncio
    async def test_service_unavailable_exception_handler_returns_503(self):
        """Covers lines 305-322: ServiceUnavailableError → 503 JSON response."""
        req = _make_mock_request()
        exc = ServiceUnavailableError("db down", service="database")
        response = await service_unavailable_exception_handler(req, exc)
        assert response.status_code == 503
        body = json.loads(response.body)
        assert body["error"]["service"] == "database"

    @pytest.mark.asyncio
    async def test_general_exception_handler_debug_mode(self):
        """Covers lines 328-338 (debug=True branch): raw error message exposed."""
        req = _make_mock_request()
        exc = RuntimeError("something broke")
        with patch("app.main.settings") as mock_settings:
            mock_settings.debug = True
            response = await general_exception_handler(req, exc)
        assert response.status_code == 500
        body = json.loads(response.body)
        assert "something broke" in body["error"]["message"]

    @pytest.mark.asyncio
    async def test_general_exception_handler_production_mode(self):
        """Covers lines 328-338 (debug=False branch): generic message shown."""
        req = _make_mock_request()
        exc = RuntimeError("internal details")
        with patch("app.main.settings") as mock_settings:
            mock_settings.debug = False
            response = await general_exception_handler(req, exc)
        assert response.status_code == 500
        body = json.loads(response.body)
        assert "internal details" not in body["error"]["message"]
        assert "internal error" in body["error"]["message"].lower()

    @pytest.mark.asyncio
    async def test_handler_with_no_request_id_on_state(self):
        """Covers getattr(request.state, 'request_id', 'unknown') fallback."""
        req = MagicMock(spec=Request)
        req.state = MagicMock(spec=[])  # no request_id attribute
        exc = OrchestratorError("oops")
        response = await orchestrator_exception_handler(req, exc)
        body = json.loads(response.body)
        assert body["error"]["request_id"] is None


# ---------------------------------------------------------------------------
# RequestLoggingMiddleware (lines 193-204)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestRequestLoggingMiddleware:
    """Cover error paths in RequestLoggingMiddleware.dispatch."""

    def _build_middleware(self):
        return RequestLoggingMiddleware(app=MagicMock())

    def _make_request(self):
        req = MagicMock(spec=Request)
        req.method = "GET"
        req.url.path = "/test"
        req.client.host = "127.0.0.1"
        req.state = MagicMock()
        return req

    @pytest.mark.asyncio
    async def test_call_next_exception_logged_and_reraised(self):
        """Covers lines 197-204: call_next raises → error logged → re-raised."""
        middleware = self._build_middleware()
        req = self._make_request()

        async def bad_call_next(r):
            raise RuntimeError("downstream exploded")

        with pytest.raises(RuntimeError, match="downstream exploded"):
            await middleware.dispatch(req, bad_call_next)

    @pytest.mark.asyncio
    async def test_metrics_recording_failure_is_swallowed(self):
        """Covers lines 193-194: record_http_request raises → except Exception: pass."""
        middleware = self._build_middleware()
        req = self._make_request()

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.headers = {}

        async def ok_call_next(r):
            return mock_response

        with patch("app.core.metrics.record_http_request", side_effect=Exception("metrics down")):
            response = await middleware.dispatch(req, ok_call_next)

        # Response is still returned even though metrics recording failed
        assert response is mock_response


# ---------------------------------------------------------------------------
# SecurityHeadersMiddleware — HTTPS path (line 366)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestSecurityHeadersMiddleware:
    @pytest.mark.asyncio
    async def test_hsts_header_added_for_https(self):
        """Covers line 366: HSTS header set when request.url.scheme == 'https'."""
        middleware = SecurityHeadersMiddleware(app=MagicMock())

        mock_request = MagicMock(spec=Request)
        mock_request.url.scheme = "https"

        mock_response = MagicMock()
        mock_response.headers = {}

        async def ok_call_next(r):
            return mock_response

        response = await middleware.dispatch(mock_request, ok_call_next)
        assert "Strict-Transport-Security" in response.headers

    @pytest.mark.asyncio
    async def test_hsts_header_absent_for_http(self):
        """HSTS header NOT added when request.url.scheme == 'http'."""
        middleware = SecurityHeadersMiddleware(app=MagicMock())

        mock_request = MagicMock(spec=Request)
        mock_request.url.scheme = "http"

        mock_response = MagicMock()
        mock_response.headers = {}

        async def ok_call_next(r):
            return mock_response

        response = await middleware.dispatch(mock_request, ok_call_next)
        assert "Strict-Transport-Security" not in response.headers


# ---------------------------------------------------------------------------
# ApiVersionHeadersMiddleware — deprecated prefix (lines 396-401)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestApiVersionHeadersMiddleware:
    @pytest.mark.asyncio
    async def test_deprecated_prefix_adds_deprecation_headers(self):
        """Covers lines 396-401: matching deprecated prefix → Deprecation/Sunset headers."""
        middleware = ApiVersionHeadersMiddleware(app=MagicMock())

        _DEPRECATED_PREFIXES["/api/v0"] = (
            "Sat, 01 Jan 2028 00:00:00 GMT",
            "https://docs.example.com/v2",
        )
        try:
            mock_request = MagicMock(spec=Request)
            mock_request.url.path = "/api/v0/agents"

            mock_response = MagicMock()
            mock_response.headers = {}

            async def ok_call_next(r):
                return mock_response

            with patch("app.main.settings") as ms:
                ms.app_version = "1.0.0"
                response = await middleware.dispatch(mock_request, ok_call_next)

            assert response.headers.get("Deprecation") == "true"
            assert "Sat, 01 Jan 2028" in response.headers.get("Sunset", "")
        finally:
            _DEPRECATED_PREFIXES.pop("/api/v0", None)

    @pytest.mark.asyncio
    async def test_non_deprecated_path_no_deprecation_headers(self):
        """No deprecated prefix → Deprecation header absent."""
        middleware = ApiVersionHeadersMiddleware(app=MagicMock())

        mock_request = MagicMock(spec=Request)
        mock_request.url.path = "/api/v1/health"

        mock_response = MagicMock()
        mock_response.headers = {}

        async def ok_call_next(r):
            return mock_response

        with patch("app.main.settings") as ms:
            ms.app_version = "1.0.0"
            response = await middleware.dispatch(mock_request, ok_call_next)

        assert "Deprecation" not in response.headers


# ---------------------------------------------------------------------------
# _check_database_liveness (line 488)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestCheckDatabaseLiveness:
    def test_success_returns_true(self):
        """Covers line 488: successful SELECT 1 → True."""
        mock_session = MagicMock()
        mock_session.execute.return_value = None

        import app.db.database as db_module

        original = db_module.SessionLocal
        db_module.SessionLocal = MagicMock(return_value=mock_session)
        try:
            result = _check_database_liveness()
            assert result is True
        finally:
            db_module.SessionLocal = original

    def test_exception_returns_false(self):
        """DB raises → returns False."""
        import app.db.database as db_module

        original = db_module.SessionLocal
        db_module.SessionLocal = MagicMock(side_effect=Exception("db down"))
        try:
            result = _check_database_liveness()
            assert result is False
        finally:
            db_module.SessionLocal = original


# ---------------------------------------------------------------------------
# /console route — 404 path (lines 453-456)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestConsoleRoute:
    def test_console_returns_404_when_file_missing(self):
        """Covers lines 453-455: console.html not found → HTTP 404."""
        app.state.container = _make_healthy_container()
        client = TestClient(app, raise_server_exceptions=False)

        with patch("app.main.Path.exists", return_value=False):
            response = client.get("/console")

        assert response.status_code == 404

    def test_console_returns_html_when_file_exists(self):
        """Covers line 456: console.html found → FileResponse returned."""
        app.state.container = _make_healthy_container()
        client = TestClient(app, raise_server_exceptions=False)
        # File exists on disk — no patching needed
        response = client.get("/console")
        assert response.status_code == 200
        assert "text/html" in response.headers.get("content-type", "")


# ---------------------------------------------------------------------------
# /metrics route (lines 470-472)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestMetricsRoute:
    def test_metrics_returns_plain_text(self):
        """Covers lines 470-472: /metrics returns Prometheus text."""
        from app.core.auth import verify_metrics_token

        app.state.container = _make_healthy_container()
        app.dependency_overrides[verify_metrics_token] = lambda: None
        client = TestClient(app, raise_server_exceptions=False)

        try:
            with patch("app.core.metrics.get_metrics", return_value="# HELP ok\nok 1\n"):
                response = client.get("/metrics")
            assert response.status_code == 200
            assert "text/plain" in response.headers["content-type"]
        finally:
            app.dependency_overrides.pop(verify_metrics_token, None)


# ---------------------------------------------------------------------------
# /api/v1/health — various edge cases (lines 521, 534-537, 545-546,
# 553-555, 560-563, 574-576)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestHealthCheckEdgeCases:
    """Direct async calls to health_check with mocked app state."""

    # Import inside tests to avoid top-level rate-limit issues
    @staticmethod
    def _get_fn():
        from app.main import health_check

        # health_check is wrapped by @limiter.limit; access unwrapped version
        fn = getattr(health_check, "__wrapped__", health_check)
        return fn

    def _request(self, container):
        req = MagicMock()
        req.app.state.container = container
        return req

    @pytest.mark.asyncio
    async def test_health_degraded_when_llm_provider_none(self):
        """Covers lines 534-537: get_provider() returns None → 'LLM provider not initialized'."""
        container = _make_healthy_container()
        container.get_llm_manager.return_value.get_provider.return_value = None

        req = self._request(container)
        fn = self._get_fn()

        with patch("app.main._check_database_liveness", return_value=True), \
             patch("app.mcp.client_manager.get_mcp_client_manager", MagicMock()), \
             patch("app.core.circuit_breaker.is_llm_breaker_open", return_value=False):
            result = await fn(req)

        assert result.status in ("degraded", "unhealthy")

    @pytest.mark.asyncio
    async def test_health_degraded_when_llm_raises(self):
        """Covers lines 534-535: get_llm_manager raises → issue appended."""
        container = _make_healthy_container()
        container.get_llm_manager.side_effect = Exception("llm unavailable")

        req = self._request(container)
        fn = self._get_fn()

        with patch("app.main._check_database_liveness", return_value=True), \
             patch("app.mcp.client_manager.get_mcp_client_manager", MagicMock()), \
             patch("app.core.circuit_breaker.is_llm_breaker_open", return_value=False):
            result = await fn(req)

        assert result.status in ("degraded", "unhealthy")

    @pytest.mark.asyncio
    async def test_health_unhealthy_when_db_unreachable(self):
        """Covers lines 560-561: 'Database not reachable' → overall_status = 'unhealthy'."""
        container = _make_healthy_container()
        req = self._request(container)
        fn = self._get_fn()

        with patch("app.main._check_database_liveness", return_value=False), \
             patch("app.mcp.client_manager.get_mcp_client_manager", MagicMock()), \
             patch("app.core.circuit_breaker.is_llm_breaker_open", return_value=False):
            result = await fn(req)

        assert result.status == "unhealthy"

    @pytest.mark.asyncio
    async def test_health_degraded_when_circuit_breaker_open(self):
        """Covers lines 521, 553-555, 562-563: breaker open → 'degraded'."""
        container = _make_healthy_container()
        req = self._request(container)
        fn = self._get_fn()

        with patch("app.main._check_database_liveness", return_value=True), \
             patch("app.mcp.client_manager.get_mcp_client_manager", MagicMock()), \
             patch("app.core.circuit_breaker.is_llm_breaker_open", return_value=True):
            result = await fn(req)

        assert result.status == "degraded"

    @pytest.mark.asyncio
    async def test_health_outer_exception_returns_unhealthy(self):
        """Covers lines 574-576: unexpected exception in try block → unhealthy."""
        container = MagicMock()
        container.get_agent_registry.side_effect = RuntimeError("crash in health check")

        req = self._request(container)
        fn = self._get_fn()

        result = await fn(req)
        assert result.status == "unhealthy"

    @pytest.mark.asyncio
    async def test_health_mcp_check_exception_swallowed(self):
        """Covers lines 545-546: MCP is_connected raises → swallowed → check continues."""
        container = _make_healthy_container()
        req = self._request(container)
        fn = self._get_fn()

        def bad_mcp_manager():
            raise ImportError("no mcp")

        with patch("app.main._check_database_liveness", return_value=True), \
             patch("app.mcp.client_manager.get_mcp_client_manager", side_effect=bad_mcp_manager), \
             patch("app.core.circuit_breaker.is_llm_breaker_open", return_value=False):
            result = await fn(req)

        # Should still return a response (mcp check failure is non-fatal)
        assert result.status == "healthy"

    @pytest.mark.asyncio
    async def test_health_unhealthy_when_no_agents_registered(self):
        """Covers line 521: agents_count == 0 → 'No agents registered' issue."""
        container = _make_healthy_container()
        container.get_agent_registry.return_value.get_all.return_value = []

        req = self._request(container)
        fn = self._get_fn()

        with patch("app.main._check_database_liveness", return_value=True), \
             patch("app.mcp.client_manager.get_mcp_client_manager", MagicMock()), \
             patch("app.core.circuit_breaker.is_llm_breaker_open", return_value=False):
            result = await fn(req)

        assert result.status == "unhealthy"

    @pytest.mark.asyncio
    async def test_health_circuit_breaker_exception_swallowed(self):
        """Covers lines 554-555: is_llm_breaker_open raises → except swallows it."""
        container = _make_healthy_container()
        req = self._request(container)
        fn = self._get_fn()

        with patch("app.main._check_database_liveness", return_value=True), \
             patch("app.mcp.client_manager.get_mcp_client_manager", MagicMock()), \
             patch("app.core.circuit_breaker.is_llm_breaker_open",
                   side_effect=RuntimeError("breaker error")):
            result = await fn(req)

        # Breaker exception is swallowed; health check still returns normally
        assert result.status == "healthy"


# ---------------------------------------------------------------------------
# Root route (line 442)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestRootRoute:
    def test_root_returns_welcome(self):
        """Covers line 442: root() returns the welcome JSON dict."""
        app.state.container = _make_healthy_container()
        client = TestClient(app, raise_server_exceptions=False)
        response = client.get("/")
        assert response.status_code == 200
        assert "AI Agent Orchestrator" in response.json()["message"]
