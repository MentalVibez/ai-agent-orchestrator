"""Unit tests for run-completion webhook delivery.

Tests:
- No-op when api_key_id is None
- No-op when key exists but webhook_url is not set
- Posts correct payload for completed / failed / cancelled / awaiting_approval events
- Swallows httpx.ConnectError (unreachable host)
- Swallows non-2xx responses (raise_for_status)
- POST /admin/keys creates key with webhook_url stored and returned
- PATCH /admin/keys/{key_id} updates webhook_url (and clears it with null)
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.database import init_db

# ---------------------------------------------------------------------------
# In-memory DB fixture
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True, scope="module")
def use_in_memory_db():
    import app.api.v1.routes.api_keys as api_keys_routes_module
    import app.core.run_store as run_store_module
    import app.core.run_webhooks as run_webhooks_module
    import app.db.database as db_module

    original_engine = db_module.engine
    original_session = db_module.SessionLocal
    original_rs_session = run_store_module.SessionLocal
    original_rw_session = run_webhooks_module.SessionLocal
    original_ak_session = api_keys_routes_module.SessionLocal

    new_engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    new_session = sessionmaker(autocommit=False, autoflush=False, bind=new_engine)

    db_module.engine = new_engine
    db_module.SessionLocal = new_session
    run_store_module.SessionLocal = new_session
    run_webhooks_module.SessionLocal = new_session
    api_keys_routes_module.SessionLocal = new_session
    init_db()

    yield new_session

    db_module.engine = original_engine
    db_module.SessionLocal = original_session
    run_store_module.SessionLocal = original_rs_session
    run_webhooks_module.SessionLocal = original_rw_session
    api_keys_routes_module.SessionLocal = original_ak_session


# ---------------------------------------------------------------------------
# Admin key + client fixtures for route-level tests
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def admin_key(use_in_memory_db):
    from app.core.api_keys import create_api_key
    db = use_in_memory_db()
    try:
        _, raw_key, _ = create_api_key(db, name="webhook-admin", role="admin")
        return raw_key
    finally:
        db.close()


@pytest.fixture(scope="module")
def client():
    from app.main import app
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


# ---------------------------------------------------------------------------
# Helper: create an ApiKeyRecord with a webhook_url in the in-memory DB
# ---------------------------------------------------------------------------

def _make_key_with_webhook(session_factory, name: str, webhook_url: str):
    from app.core.api_keys import create_api_key
    db = session_factory()
    try:
        key_id, _, _ = create_api_key(db, name=name, role="operator", webhook_url=webhook_url)
        return key_id
    finally:
        db.close()


def _make_key_no_webhook(session_factory, name: str):
    from app.core.api_keys import create_api_key
    db = session_factory()
    try:
        key_id, _, _ = create_api_key(db, name=name, role="operator")
        return key_id
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Tests: notify_run_terminal core behaviour
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestNotifyRunTerminal:
    @pytest.mark.asyncio
    async def test_noop_when_api_key_id_is_none(self):
        """No DB lookup and no POST when api_key_id is None."""
        from app.core.run_webhooks import notify_run_terminal

        with patch("app.core.run_webhooks.httpx") as mock_httpx:
            await notify_run_terminal("run-1", "test goal", "completed", api_key_id=None)
            mock_httpx.AsyncClient.assert_not_called()

    @pytest.mark.asyncio
    async def test_noop_when_no_webhook_url(self, use_in_memory_db):
        """No POST when the API key has no webhook_url configured."""
        from app.core.run_webhooks import notify_run_terminal

        key_id = _make_key_no_webhook(use_in_memory_db, "no-webhook-key")
        with patch("app.core.run_webhooks.httpx") as mock_httpx:
            await notify_run_terminal("run-2", "goal", "completed", api_key_id=key_id)
            mock_httpx.AsyncClient.assert_not_called()

    @pytest.mark.asyncio
    async def test_posts_correct_payload_on_completed(self, use_in_memory_db):
        """On completed, POSTs event=run.completed with answer field."""
        from app.core.run_webhooks import notify_run_terminal

        key_id = _make_key_with_webhook(use_in_memory_db, "completed-key", "https://example.com/hook")

        mock_resp = MagicMock()
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("app.core.run_webhooks.httpx") as mock_httpx:
            mock_httpx.AsyncClient.return_value = mock_client
            await notify_run_terminal(
                "run-3", "restart nginx", "completed",
                api_key_id=key_id, answer="Service restarted."
            )

        mock_client.post.assert_called_once()
        url, kwargs = mock_client.post.call_args[0][0], mock_client.post.call_args[1]
        assert url == "https://example.com/hook"
        payload = kwargs["json"]
        assert payload["event"] == "run.completed"
        assert payload["run_id"] == "run-3"
        assert payload["goal"] == "restart nginx"
        assert payload["status"] == "completed"
        assert payload["answer"] == "Service restarted."
        assert payload["error"] is None

    @pytest.mark.asyncio
    async def test_posts_correct_payload_on_failed(self, use_in_memory_db):
        """On failed, POSTs event=run.failed with error field."""
        from app.core.run_webhooks import notify_run_terminal

        key_id = _make_key_with_webhook(use_in_memory_db, "failed-key", "https://example.com/hook")

        mock_resp = MagicMock()
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("app.core.run_webhooks.httpx") as mock_httpx:
            mock_httpx.AsyncClient.return_value = mock_client
            await notify_run_terminal(
                "run-4", "diagnose disk", "failed",
                api_key_id=key_id, error="LLM call timed out"
            )

        payload = mock_client.post.call_args[1]["json"]
        assert payload["event"] == "run.failed"
        assert payload["error"] == "LLM call timed out"
        assert payload["answer"] is None

    @pytest.mark.asyncio
    async def test_posts_correct_payload_on_cancelled(self, use_in_memory_db):
        """On cancelled, POSTs event=run.cancelled."""
        from app.core.run_webhooks import notify_run_terminal

        key_id = _make_key_with_webhook(use_in_memory_db, "cancelled-key", "https://example.com/hook")

        mock_resp = MagicMock()
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("app.core.run_webhooks.httpx") as mock_httpx:
            mock_httpx.AsyncClient.return_value = mock_client
            await notify_run_terminal("run-5", "check uptime", "cancelled", api_key_id=key_id)

        payload = mock_client.post.call_args[1]["json"]
        assert payload["event"] == "run.cancelled"

    @pytest.mark.asyncio
    async def test_posts_correct_payload_on_awaiting_approval(self, use_in_memory_db):
        """On awaiting_approval, POSTs event=run.awaiting_approval."""
        from app.core.run_webhooks import notify_run_terminal

        key_id = _make_key_with_webhook(use_in_memory_db, "approval-key", "https://example.com/hook")

        mock_resp = MagicMock()
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("app.core.run_webhooks.httpx") as mock_httpx:
            mock_httpx.AsyncClient.return_value = mock_client
            await notify_run_terminal("run-6", "reboot server", "awaiting_approval", api_key_id=key_id)

        payload = mock_client.post.call_args[1]["json"]
        assert payload["event"] == "run.awaiting_approval"

    @pytest.mark.asyncio
    async def test_adds_signature_headers_when_secret_configured(self, use_in_memory_db):
        """When outbound secret is set, webhook includes verifiable HMAC headers."""
        import hashlib
        import hmac
        import json

        from app.core.run_webhooks import notify_run_terminal

        key_id = _make_key_with_webhook(use_in_memory_db, "signed-key", "https://example.com/hook")

        mock_resp = MagicMock()
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("app.core.run_webhooks.httpx") as mock_httpx:
            with patch("app.core.run_webhooks.time.time", return_value=1700000000):
                with patch("app.core.run_webhooks.settings") as mock_settings:
                    mock_settings.outbound_webhook_secret = "test-secret"
                    mock_settings.webhook_secret = ""
                    mock_httpx.AsyncClient.return_value = mock_client
                    await notify_run_terminal(
                        "run-9", "signed goal", "completed", api_key_id=key_id, answer="ok"
                    )

        kwargs = mock_client.post.call_args[1]
        payload = kwargs["json"]
        headers = kwargs["headers"]
        assert headers["X-Webhook-Timestamp"] == "1700000000"

        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        expected = hmac.new(
            b"test-secret",
            f"1700000000.{canonical}".encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        assert headers["X-Webhook-Signature"] == f"sha256={expected}"

    @pytest.mark.asyncio
    async def test_swallows_connect_error(self, use_in_memory_db):
        """ConnectError should be swallowed — no raise."""
        import httpx as _httpx

        from app.core.run_webhooks import notify_run_terminal

        key_id = _make_key_with_webhook(use_in_memory_db, "conn-err-key", "https://unreachable.example/hook")

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(side_effect=_httpx.ConnectError("connection refused"))
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("app.core.run_webhooks.httpx") as mock_httpx:
            mock_httpx.AsyncClient.return_value = mock_client
            mock_httpx.ConnectError = _httpx.ConnectError
            # Must not raise
            await notify_run_terminal("run-7", "goal", "completed", api_key_id=key_id)

    @pytest.mark.asyncio
    async def test_swallows_http_status_error(self, use_in_memory_db):
        """Non-2xx response (raise_for_status) should be swallowed — no raise."""
        import httpx as _httpx

        from app.core.run_webhooks import notify_run_terminal

        key_id = _make_key_with_webhook(use_in_memory_db, "status-err-key", "https://example.com/hook")

        mock_resp = MagicMock()
        mock_resp.raise_for_status.side_effect = _httpx.HTTPStatusError(
            "500", request=MagicMock(), response=MagicMock()
        )
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("app.core.run_webhooks.httpx") as mock_httpx:
            mock_httpx.AsyncClient.return_value = mock_client
            # Must not raise
            await notify_run_terminal("run-8", "goal", "completed", api_key_id=key_id)


# ---------------------------------------------------------------------------
# Tests: API key management routes
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestApiKeyWebhookRoutes:
    def test_create_key_with_webhook_url(self, client, admin_key):
        """POST /admin/keys with webhook_url stores and returns it."""
        resp = client.post(
            "/api/v1/admin/keys",
            json={
                "name": "key-with-hook",
                "role": "operator",
                "webhook_url": "https://hooks.example.com/run-events",
            },
            headers={"X-API-Key": admin_key},
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["webhook_url"] == "https://hooks.example.com/run-events"

    def test_create_key_without_webhook_url(self, client, admin_key):
        """POST /admin/keys without webhook_url returns None."""
        resp = client.post(
            "/api/v1/admin/keys",
            json={"name": "key-no-hook", "role": "operator"},
            headers={"X-API-Key": admin_key},
        )
        assert resp.status_code == 201
        assert resp.json()["webhook_url"] is None

    def test_patch_key_updates_webhook_url(self, client, admin_key, use_in_memory_db):
        """PATCH /admin/keys/{key_id} updates webhook_url."""
        # Create a key first
        create_resp = client.post(
            "/api/v1/admin/keys",
            json={"name": "patch-test-key", "role": "operator"},
            headers={"X-API-Key": admin_key},
        )
        key_id = create_resp.json()["key_id"]

        patch_resp = client.patch(
            f"/api/v1/admin/keys/{key_id}",
            json={"webhook_url": "https://new.example.com/webhook"},
            headers={"X-API-Key": admin_key},
        )
        assert patch_resp.status_code == 200
        assert patch_resp.json()["webhook_url"] == "https://new.example.com/webhook"

    def test_patch_key_404_for_unknown(self, client, admin_key):
        """PATCH for unknown key_id returns 404."""
        resp = client.patch(
            "/api/v1/admin/keys/kid_doesnotexist",
            json={"webhook_url": "https://example.com"},
            headers={"X-API-Key": admin_key},
        )
        assert resp.status_code == 404





