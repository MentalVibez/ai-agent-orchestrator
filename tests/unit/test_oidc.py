"""Unit tests for app/core/oidc.py — JWKS cache and JWT validation."""

import json
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from starlette.requests import Request
from starlette.types import Scope


def _make_request() -> Request:
    """Build a minimal Starlette Request with a writable state."""
    scope: Scope = {
        "type": "http",
        "method": "GET",
        "path": "/",
        "query_string": b"",
        "headers": [],
    }
    request = Request(scope)
    return request


# ---------------------------------------------------------------------------
# Tests: JWKS cache helpers
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestJwksCache:
    def setup_method(self):
        """Reset cache state before each test."""
        import app.core.oidc as oidc_module

        oidc_module._jwks_keys = []
        oidc_module._jwks_fetched_at = None

    def test_cache_is_stale_when_never_fetched(self):
        from app.core.oidc import _is_cache_fresh

        assert _is_cache_fresh() is False

    def test_cache_is_fresh_within_ttl(self):
        import app.core.oidc as oidc_module
        from app.core.oidc import _is_cache_fresh

        oidc_module._jwks_fetched_at = datetime.now(timezone.utc)
        with patch("app.core.config.settings") as mock_settings:
            mock_settings.oidc_jwks_cache_ttl = 86400
            assert _is_cache_fresh() is True

    def test_cache_is_stale_after_ttl(self):
        import app.core.oidc as oidc_module
        from app.core.oidc import _is_cache_fresh

        oidc_module._jwks_fetched_at = datetime.now(timezone.utc) - timedelta(hours=25)
        with patch("app.core.config.settings") as mock_settings:
            mock_settings.oidc_jwks_cache_ttl = 86400
            assert _is_cache_fresh() is False

    @pytest.mark.asyncio
    async def test_get_jwks_calls_fetch_when_stale(self):
        from app.core.oidc import _get_jwks

        fake_keys = [{"kid": "key1", "kty": "RSA"}]
        with patch("app.core.oidc._fetch_jwks", new=AsyncMock(return_value=fake_keys)):
            result = await _get_jwks()
        assert result == fake_keys

    @pytest.mark.asyncio
    async def test_get_jwks_uses_cache_when_fresh(self):
        import app.core.oidc as oidc_module
        from app.core.oidc import _get_jwks

        cached_keys = [{"kid": "cached", "kty": "RSA"}]
        oidc_module._jwks_keys = cached_keys
        oidc_module._jwks_fetched_at = datetime.now(timezone.utc)

        with patch("app.core.config.settings") as mock_settings:
            mock_settings.oidc_jwks_cache_ttl = 86400
            with patch("app.core.oidc._fetch_jwks", new=AsyncMock()) as mock_fetch:
                result = await _get_jwks()
                mock_fetch.assert_not_called()
        assert result == cached_keys

    @pytest.mark.asyncio
    async def test_get_jwks_serves_stale_on_fetch_failure(self):
        import app.core.oidc as oidc_module
        from app.core.oidc import _get_jwks

        stale_keys = [{"kid": "stale-key", "kty": "RSA"}]
        oidc_module._jwks_keys = stale_keys
        oidc_module._jwks_fetched_at = None  # Mark as stale

        with patch("app.core.oidc._fetch_jwks", new=AsyncMock(side_effect=Exception("timeout"))):
            result = await _get_jwks()
        assert result == stale_keys

    @pytest.mark.asyncio
    async def test_get_jwks_raises_503_when_fetch_fails_and_no_cache(self):
        import app.core.oidc as oidc_module
        from app.core.oidc import _get_jwks

        oidc_module._jwks_keys = []
        oidc_module._jwks_fetched_at = None

        with patch("app.core.oidc._fetch_jwks", new=AsyncMock(side_effect=Exception("unreachable"))):
            with pytest.raises(HTTPException) as exc_info:
                await _get_jwks()
        assert exc_info.value.status_code == 503


# ---------------------------------------------------------------------------
# Tests: _map_role
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestMapRole:
    def test_returns_viewer_when_no_match(self):
        from app.core.oidc import _map_role

        with patch("app.core.config.settings") as mock_settings:
            mock_settings.oidc_role_claim = "roles"
            mock_settings.oidc_role_map = json.dumps({"platform-admin": "admin"})
            result = _map_role({"roles": ["random-group"]})
        assert result == "viewer"

    def test_maps_string_claim_to_admin(self):
        from app.core.oidc import _map_role

        with patch("app.core.config.settings") as mock_settings:
            mock_settings.oidc_role_claim = "roles"
            mock_settings.oidc_role_map = json.dumps({"platform-admin": "admin"})
            result = _map_role({"roles": "platform-admin"})
        assert result == "admin"

    def test_maps_list_claim_highest_wins(self):
        from app.core.oidc import _map_role

        with patch("app.core.config.settings") as mock_settings:
            mock_settings.oidc_role_claim = "roles"
            mock_settings.oidc_role_map = json.dumps({
                "read-only": "viewer",
                "dev-team": "operator",
                "platform-admin": "admin",
            })
            result = _map_role({"roles": ["read-only", "dev-team", "platform-admin"]})
        assert result == "admin"

    def test_operator_beats_viewer(self):
        from app.core.oidc import _map_role

        with patch("app.core.config.settings") as mock_settings:
            mock_settings.oidc_role_claim = "groups"
            mock_settings.oidc_role_map = json.dumps({"eng": "operator", "all": "viewer"})
            result = _map_role({"groups": ["all", "eng"]})
        assert result == "operator"

    def test_invalid_role_map_json_defaults_to_viewer(self):
        from app.core.oidc import _map_role

        with patch("app.core.config.settings") as mock_settings:
            mock_settings.oidc_role_claim = "roles"
            mock_settings.oidc_role_map = "not-valid-json"
            result = _map_role({"roles": ["platform-admin"]})
        assert result == "viewer"

    def test_missing_claim_returns_viewer(self):
        from app.core.oidc import _map_role

        with patch("app.core.config.settings") as mock_settings:
            mock_settings.oidc_role_claim = "roles"
            mock_settings.oidc_role_map = json.dumps({"admin-group": "admin"})
            result = _map_role({"sub": "user-123"})  # no "roles" key
        assert result == "viewer"

    def test_empty_role_map_returns_viewer(self):
        from app.core.oidc import _map_role

        with patch("app.core.config.settings") as mock_settings:
            mock_settings.oidc_role_claim = "roles"
            mock_settings.oidc_role_map = "{}"
            result = _map_role({"roles": ["admin-group"]})
        assert result == "viewer"


# ---------------------------------------------------------------------------
# Tests: verify_oidc_token
# ---------------------------------------------------------------------------


def _make_mock_rsa_key():
    """Create a mock RSA key object."""
    mock_key = MagicMock()
    return mock_key


@pytest.mark.unit
class TestVerifyOidcToken:
    def setup_method(self):
        import app.core.oidc as oidc_module

        oidc_module._jwks_keys = [{"kid": "test-kid", "kty": "RSA", "n": "abc", "e": "AQAB"}]
        oidc_module._jwks_fetched_at = datetime.now(timezone.utc)

    @pytest.mark.asyncio
    async def test_valid_token_populates_request_state(self):
        from app.core.oidc import verify_oidc_token

        request = _make_request()
        claims = {"sub": "user-abc", "roles": ["admin-group"], "exp": 9999999999}
        fake_key = MagicMock()

        with patch("app.core.config.settings") as mock_settings:
            mock_settings.oidc_jwks_cache_ttl = 86400
            mock_settings.oidc_issuer = ""
            mock_settings.oidc_audience = ""
            mock_settings.oidc_role_claim = "roles"
            mock_settings.oidc_role_map = json.dumps({"admin-group": "admin"})

            with patch("app.core.oidc._get_jwks", new=AsyncMock(return_value=[{"kid": "test-kid"}])):
                with patch("jwt.get_unverified_header", return_value={"kid": "test-kid", "alg": "RS256"}):
                    with patch("jwt.algorithms.RSAAlgorithm.from_jwk", return_value=fake_key):
                        with patch("jwt.decode", return_value=claims):
                            result = await verify_oidc_token(request, "fake.jwt.token")

        assert result == "fake.jwt.token"
        assert request.state.api_key_id == "oidc:user-abc"
        assert request.state.api_key_role == "admin"

    @pytest.mark.asyncio
    async def test_invalid_header_raises_401(self):
        import jwt as pyjwt

        from app.core.oidc import verify_oidc_token

        request = _make_request()

        with patch("app.core.oidc._get_jwks", new=AsyncMock(return_value=[{"kid": "k1"}])):
            with patch("jwt.get_unverified_header", side_effect=pyjwt.exceptions.DecodeError("bad header")):
                with pytest.raises(HTTPException) as exc_info:
                    await verify_oidc_token(request, "bad-token")
        assert exc_info.value.status_code == 401

    @pytest.mark.asyncio
    async def test_no_matching_key_raises_401(self):
        from app.core.oidc import verify_oidc_token

        request = _make_request()

        with patch("app.core.oidc._get_jwks", new=AsyncMock(return_value=[])):
            with patch("jwt.get_unverified_header", return_value={"kid": "unknown-kid", "alg": "RS256"}):
                with pytest.raises(HTTPException) as exc_info:
                    await verify_oidc_token(request, "fake.jwt.token")
        assert exc_info.value.status_code == 401

    @pytest.mark.asyncio
    async def test_expired_token_raises_401(self):
        import jwt as pyjwt

        from app.core.oidc import verify_oidc_token

        request = _make_request()
        fake_key = MagicMock()

        with patch("app.core.config.settings") as mock_settings:
            mock_settings.oidc_issuer = ""
            mock_settings.oidc_audience = ""
            mock_settings.oidc_role_claim = "roles"
            mock_settings.oidc_role_map = "{}"

            with patch("app.core.oidc._get_jwks", new=AsyncMock(return_value=[{"kid": "k1"}])):
                with patch("jwt.get_unverified_header", return_value={"kid": "k1", "alg": "RS256"}):
                    with patch("jwt.algorithms.RSAAlgorithm.from_jwk", return_value=fake_key):
                        with patch("jwt.decode", side_effect=pyjwt.exceptions.ExpiredSignatureError("expired")):
                            with pytest.raises(HTTPException) as exc_info:
                                await verify_oidc_token(request, "expired.jwt.token")
        assert exc_info.value.status_code == 401

    @pytest.mark.asyncio
    async def test_sub_used_as_key_id_prefix(self):
        from app.core.oidc import verify_oidc_token

        request = _make_request()
        claims = {"sub": "sub-xyz-789", "exp": 9999999999}
        fake_key = MagicMock()

        with patch("app.core.config.settings") as mock_settings:
            mock_settings.oidc_issuer = ""
            mock_settings.oidc_audience = ""
            mock_settings.oidc_role_claim = "roles"
            mock_settings.oidc_role_map = "{}"

            with patch("app.core.oidc._get_jwks", new=AsyncMock(return_value=[{"kid": "k1"}])):
                with patch("jwt.get_unverified_header", return_value={"kid": "k1", "alg": "RS256"}):
                    with patch("jwt.algorithms.RSAAlgorithm.from_jwk", return_value=fake_key):
                        with patch("jwt.decode", return_value=claims):
                            await verify_oidc_token(request, "some.jwt.token")

        assert request.state.api_key_id == "oidc:sub-xyz-789"


# ---------------------------------------------------------------------------
# Tests: OIDC integration with verify_api_key
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestOidcIntegrationWithAuth:
    @pytest.mark.asyncio
    async def test_bearer_token_triggers_oidc_when_enabled(self):
        """When OIDC_ENABLED=True and Authorization: Bearer present, OIDC path is used."""
        from app.core.auth import verify_api_key

        scope = {
            "type": "http",
            "method": "GET",
            "path": "/",
            "query_string": b"",
            "headers": [(b"authorization", b"Bearer my.jwt.token")],
        }
        request = Request(scope)
        mock_oidc = AsyncMock(return_value="my.jwt.token")

        with patch("app.core.config.settings") as mock_settings:
            mock_settings.oidc_enabled = True
            mock_settings.require_api_key = True
            mock_settings.api_key = ""
            with patch("app.core.auth.settings", mock_settings):
                # verify_oidc_token is imported inside the function body in auth.py
                # so patch it at its source module (app.core.oidc)
                with patch("app.core.oidc.verify_oidc_token", mock_oidc):
                    result = await verify_api_key(request, api_key="")

        mock_oidc.assert_called_once_with(request, "my.jwt.token")
        assert result == "my.jwt.token"

    @pytest.mark.asyncio
    async def test_oidc_disabled_skips_bearer_path(self):
        """When OIDC_ENABLED=False, Authorization: Bearer header is ignored."""
        from app.core.auth import verify_api_key

        scope = {
            "type": "http",
            "method": "GET",
            "path": "/",
            "query_string": b"",
            "headers": [(b"authorization", b"Bearer my.jwt.token")],
        }
        request = Request(scope)
        mock_oidc = AsyncMock()

        with patch("app.core.config.settings") as mock_settings:
            mock_settings.oidc_enabled = False
            mock_settings.require_api_key = False  # skip key check

            with patch("app.core.auth.settings", mock_settings):
                with patch("app.core.oidc.verify_oidc_token", mock_oidc):
                    await verify_api_key(request, api_key="ignored")

        mock_oidc.assert_not_called()

    def test_oidc_verify_function_importable(self):
        from app.core.oidc import verify_oidc_token

        assert callable(verify_oidc_token)

    def test_map_role_importable(self):
        from app.core.oidc import _map_role

        assert callable(_map_role)

    def test_get_jwks_importable(self):
        from app.core.oidc import _get_jwks

        assert callable(_get_jwks)

