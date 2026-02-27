"""Unit tests for app/core/auth.py — including the new DB registry and RBAC."""

from unittest.mock import patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from starlette.requests import Request

from app.core.auth import require_role, verify_api_key, verify_metrics_token
from app.core.config import settings
from app.db.database import init_db

# ---------------------------------------------------------------------------
# Module-level in-memory DB
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True, scope="module")
def use_in_memory_db():
    import app.core.persistence as persistence_module
    import app.core.run_store as run_store_module
    import app.db.database as db_module

    orig_engine = db_module.engine
    orig_session = db_module.SessionLocal
    orig_run_store = run_store_module.SessionLocal
    orig_persistence = persistence_module.SessionLocal

    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    session = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    db_module.engine = engine
    db_module.SessionLocal = session
    run_store_module.SessionLocal = session
    persistence_module.SessionLocal = session

    init_db()
    yield

    db_module.engine = orig_engine
    db_module.SessionLocal = orig_session
    run_store_module.SessionLocal = orig_run_store
    persistence_module.SessionLocal = orig_persistence


# ---------------------------------------------------------------------------
# Helper: fake Request object
# ---------------------------------------------------------------------------


def _fake_request(headers: dict | None = None):
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/test",
        "query_string": b"",
        "headers": [(k.lower().encode(), v.encode()) for k, v in (headers or {}).items()],
    }
    return Request(scope)


# ---------------------------------------------------------------------------
# Tests: verify_api_key — auth disabled path
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestVerifyApiKeyAuthDisabled:
    @pytest.mark.asyncio
    async def test_allows_any_request_when_auth_disabled(self):
        original_require = settings.require_api_key
        settings.require_api_key = False
        try:
            request = _fake_request()
            request.state  # touch state to initialise it
            result = await verify_api_key(request, api_key=None)
            assert result == "no-key-required"
        finally:
            settings.require_api_key = original_require

    @pytest.mark.asyncio
    async def test_returns_provided_key_when_auth_disabled(self):
        original_require = settings.require_api_key
        settings.require_api_key = False
        try:
            request = _fake_request()
            result = await verify_api_key(request, api_key="any-key")
            assert result == "any-key"
        finally:
            settings.require_api_key = original_require


# ---------------------------------------------------------------------------
# Tests: verify_api_key — env-var bootstrap key
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestVerifyApiKeyEnvBootstrap:
    @pytest.mark.asyncio
    async def test_env_key_grants_access(self):
        orig_require = settings.require_api_key
        orig_key = settings.api_key
        settings.require_api_key = True
        settings.api_key = "bootstrap-secret"
        try:
            request = _fake_request()
            # Patch lookup at source module; SessionLocal is resolved from app.db.database
            # at call time (inside function body) so the in-memory DB fixture handles it.
            with patch("app.core.api_keys.lookup_api_key", return_value=None):
                result = await verify_api_key(request, api_key="bootstrap-secret")
                assert result == "bootstrap-secret"
                assert request.state.api_key_role == "admin"
        finally:
            settings.require_api_key = orig_require
            settings.api_key = orig_key

    @pytest.mark.asyncio
    async def test_wrong_env_key_raises_401(self):
        from fastapi import HTTPException

        orig_require = settings.require_api_key
        orig_key = settings.api_key
        settings.require_api_key = True
        settings.api_key = "correct-key"
        try:
            request = _fake_request()
            with patch("app.core.api_keys.lookup_api_key", return_value=None):
                with pytest.raises(HTTPException) as exc_info:
                    await verify_api_key(request, api_key="wrong-key")
                assert exc_info.value.status_code == 401
        finally:
            settings.require_api_key = orig_require
            settings.api_key = orig_key

    @pytest.mark.asyncio
    async def test_missing_key_raises_401(self):
        from fastapi import HTTPException

        orig_require = settings.require_api_key
        orig_key = settings.api_key
        settings.require_api_key = True
        settings.api_key = "some-key"
        try:
            request = _fake_request()
            with pytest.raises(HTTPException) as exc_info:
                await verify_api_key(request, api_key=None)
            assert exc_info.value.status_code == 401
        finally:
            settings.require_api_key = orig_require
            settings.api_key = orig_key

    @pytest.mark.asyncio
    async def test_no_key_configured_at_all_raises_503(self):
        from fastapi import HTTPException

        orig_require = settings.require_api_key
        orig_key = settings.api_key
        settings.require_api_key = True
        settings.api_key = ""
        try:
            request = _fake_request()
            with patch("app.core.api_keys.lookup_api_key", return_value=None):
                with pytest.raises(HTTPException) as exc_info:
                    await verify_api_key(request, api_key="anything")
                assert exc_info.value.status_code == 503
        finally:
            settings.require_api_key = orig_require
            settings.api_key = orig_key


# ---------------------------------------------------------------------------
# Tests: verify_api_key — DB key registry path
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestVerifyApiKeyDbRegistry:
    @pytest.mark.asyncio
    async def test_db_key_grants_access_with_role(self):
        orig_require = settings.require_api_key
        settings.require_api_key = True
        try:
            from unittest.mock import MagicMock

            # Use a plain MagicMock to avoid SQLAlchemy DetachedInstanceError.
            mock_record = MagicMock()
            mock_record.role = "operator"
            mock_record.key_id = "kid_abc"
            request = _fake_request()

            # lookup_api_key is imported inside verify_api_key's function body via
            # `from app.core.api_keys import lookup_api_key`, so patch the source.
            with patch("app.core.api_keys.lookup_api_key", return_value=mock_record):
                result = await verify_api_key(request, api_key="orc_some-valid-key")
                assert result == "orc_some-valid-key"
                assert request.state.api_key_role == "operator"
                assert request.state.api_key_id == "kid_abc"
        finally:
            settings.require_api_key = orig_require


# ---------------------------------------------------------------------------
# Tests: require_role dependency
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestRequireRole:
    @pytest.mark.asyncio
    async def test_passes_when_role_meets_minimum(self):
        request = _fake_request()
        request.state.api_key_role = "admin"
        checker = require_role("operator")
        # Should not raise
        await checker(request)

    @pytest.mark.asyncio
    async def test_raises_403_when_role_insufficient(self):
        from fastapi import HTTPException

        request = _fake_request()
        request.state.api_key_role = "viewer"
        checker = require_role("admin")
        with pytest.raises(HTTPException) as exc_info:
            await checker(request)
        assert exc_info.value.status_code == 403

    @pytest.mark.asyncio
    async def test_viewer_passes_viewer_requirement(self):
        request = _fake_request()
        request.state.api_key_role = "viewer"
        checker = require_role("viewer")
        await checker(request)

    @pytest.mark.asyncio
    async def test_operator_fails_admin_requirement(self):
        from fastapi import HTTPException

        request = _fake_request()
        request.state.api_key_role = "operator"
        checker = require_role("admin")
        with pytest.raises(HTTPException) as exc_info:
            await checker(request)
        assert exc_info.value.status_code == 403


# ---------------------------------------------------------------------------
# Tests: verify_metrics_token
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestVerifyMetricsToken:
    @pytest.mark.asyncio
    async def test_x_metrics_token_header_accepted(self):
        orig = settings.metrics_token
        settings.metrics_token = "metrics-secret"
        try:
            request = _fake_request({"X-Metrics-Token": "metrics-secret"})
            # Should not raise
            await verify_metrics_token(request)
        finally:
            settings.metrics_token = orig

    @pytest.mark.asyncio
    async def test_bearer_token_accepted(self):
        orig = settings.metrics_token
        settings.metrics_token = "metrics-secret"
        try:
            request = _fake_request({"Authorization": "Bearer metrics-secret"})
            await verify_metrics_token(request)
        finally:
            settings.metrics_token = orig

    @pytest.mark.asyncio
    async def test_wrong_metrics_token_raises_401(self):
        from fastapi import HTTPException

        orig = settings.metrics_token
        settings.metrics_token = "metrics-secret"
        try:
            request = _fake_request({"X-Metrics-Token": "wrong-token"})
            with pytest.raises(HTTPException) as exc_info:
                await verify_metrics_token(request)
            assert exc_info.value.status_code == 401
        finally:
            settings.metrics_token = orig

    @pytest.mark.asyncio
    async def test_missing_metrics_token_raises_401(self):
        from fastapi import HTTPException

        orig = settings.metrics_token
        settings.metrics_token = "metrics-secret"
        try:
            request = _fake_request()
            with pytest.raises(HTTPException) as exc_info:
                await verify_metrics_token(request)
            assert exc_info.value.status_code == 401
        finally:
            settings.metrics_token = orig

    @pytest.mark.asyncio
    async def test_falls_back_to_api_key_when_no_metrics_token_set(self):
        """When METRICS_TOKEN is empty, falls back to verify_api_key logic."""
        orig = settings.metrics_token
        orig_require = settings.require_api_key
        settings.metrics_token = ""
        settings.require_api_key = False
        try:
            request = _fake_request()
            # Should not raise — falls back to disabled auth
            await verify_metrics_token(request)
        finally:
            settings.metrics_token = orig
            settings.require_api_key = orig_require
