"""Unit tests for DEX self-healing engine (app/core/dex/self_healing.py)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.database import init_db
from app.db.models import DexAlert

# ---------------------------------------------------------------------------
# Module-level DB patch
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True, scope="module")
def use_in_memory_db():
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


@pytest.fixture
def db(use_in_memory_db):
    from app.db.database import SessionLocal

    session = SessionLocal()
    yield session
    session.close()


@pytest.fixture
def active_alert(db):
    """A persisted active DexAlert for use across tests."""
    alert = DexAlert(
        hostname="healer-host",
        alert_name="DiskFull",
        severity="warning",
        alert_type="threshold",
        message="Disk at 92%",
        status="active",
    )
    db.add(alert)
    db.commit()
    db.refresh(alert)
    return alert


# ---------------------------------------------------------------------------
# _build_goal
# ---------------------------------------------------------------------------


class TestBuildGoal:
    def test_ansible_action(self):
        from app.core.dex.self_healing import _build_goal

        config = {"action": "ansible", "playbook": "cleanup_disk"}
        alert = DexAlert(hostname="myhost", message="disk full", alert_name="DiskFull")
        goal = _build_goal(config, alert)
        assert "cleanup_disk" in goal
        assert "myhost" in goal

    def test_restart_action(self):
        from app.core.dex.self_healing import _build_goal

        config = {"action": "restart", "service": "nginx"}
        alert = DexAlert(hostname="webhost", message="nginx down", alert_name="ServiceDown")
        goal = _build_goal(config, alert)
        assert "nginx" in goal
        assert "webhost" in goal

    def test_clear_cache_action(self):
        from app.core.dex.self_healing import _build_goal

        config = {"action": "clear_cache"}
        alert = DexAlert(hostname="host1", message="oom", alert_name="HighMemory")
        goal = _build_goal(config, alert)
        assert "cache" in goal.lower()
        assert "host1" in goal

    def test_unknown_action_falls_back_to_diagnose(self):
        from app.core.dex.self_healing import _build_goal

        config = {"action": "magic"}
        alert = DexAlert(hostname="xhost", message="unknown issue", alert_name="Weird")
        goal = _build_goal(config, alert)
        assert "xhost" in goal
        assert len(goal) > 10


# ---------------------------------------------------------------------------
# _load_remediation_map
# ---------------------------------------------------------------------------


class TestLoadRemediationMap:
    def test_returns_dict(self):
        from app.core.dex.self_healing import _load_remediation_map

        result = _load_remediation_map()
        assert isinstance(result, dict)

    def test_missing_file_returns_empty(self, tmp_path):
        import app.core.dex.self_healing as sh_module

        original = sh_module._REMEDIATION_MAP_PATH
        try:
            sh_module._REMEDIATION_MAP_PATH = tmp_path / "nonexistent.yaml"
            result = sh_module._load_remediation_map()
            assert result == {}
        finally:
            sh_module._REMEDIATION_MAP_PATH = original

    def test_malformed_yaml_returns_empty(self, tmp_path):
        import app.core.dex.self_healing as sh_module

        bad_file = tmp_path / "bad.yaml"
        bad_file.write_text(": : : invalid yaml :\n{{{{", encoding="utf-8")
        original = sh_module._REMEDIATION_MAP_PATH
        try:
            sh_module._REMEDIATION_MAP_PATH = bad_file
            result = sh_module._load_remediation_map()
            assert result == {}
        finally:
            sh_module._REMEDIATION_MAP_PATH = original


# ---------------------------------------------------------------------------
# handle_alert
# ---------------------------------------------------------------------------


class TestHandleAlert:
    @pytest.mark.asyncio
    async def test_skips_non_active_alert(self, db):
        from app.core.dex.self_healing import handle_alert

        alert = DexAlert(hostname="h", alert_name="X", status="acknowledged")
        db.add(alert)
        db.commit()
        result = await handle_alert(db, alert)
        assert result["action"] == "skipped"
        assert "acknowledged" in result["reason"]

    @pytest.mark.asyncio
    async def test_no_mapping_escalates_to_ticket(self, db, active_alert):
        from app.core.dex.self_healing import handle_alert

        with patch(
            "app.core.dex.self_healing._load_remediation_map", return_value={}
        ), patch(
            "app.core.dex.self_healing._send_ticket_webhook", new=AsyncMock()
        ) as mock_ticket:
            result = await handle_alert(db, active_alert)

        assert result["action"] == "ticket"
        assert result["reason"] == "no_remediation_mapping"
        mock_ticket.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_explicit_ticket_action(self, db):
        from app.core.dex.self_healing import handle_alert

        alert = DexAlert(
            hostname="ticket-host",
            alert_name="KernelPanic",
            status="active",
            message="kernel oops",
        )
        db.add(alert)
        db.commit()
        db.refresh(alert)

        with patch(
            "app.core.dex.self_healing._load_remediation_map",
            return_value={"KernelPanic": {"action": "ticket", "severity": "critical"}},
        ), patch(
            "app.core.dex.self_healing._send_ticket_webhook", new=AsyncMock()
        ) as mock_ticket:
            result = await handle_alert(db, alert)

        assert result["action"] == "ticket"
        assert result["reason"] == "explicit_ticket_mapping"
        mock_ticket.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_self_healing_disabled_sends_ticket(self, db):
        from app.core.config import settings
        from app.core.dex.self_healing import handle_alert

        alert = DexAlert(
            hostname="disabled-host",
            alert_name="DiskFull",
            status="active",
            message="disk 95%",
        )
        db.add(alert)
        db.commit()
        db.refresh(alert)

        original = settings.dex_self_healing_enabled
        try:
            settings.dex_self_healing_enabled = False
            with patch(
                "app.core.dex.self_healing._load_remediation_map",
                return_value={
                    "DiskFull": {"action": "ansible", "playbook": "cleanup_disk"}
                },
            ), patch(
                "app.core.dex.self_healing._send_ticket_webhook", new=AsyncMock()
            ) as mock_ticket:
                result = await handle_alert(db, alert)
        finally:
            settings.dex_self_healing_enabled = original

        assert result["action"] == "ticket"
        assert result["reason"] == "self_healing_disabled"
        mock_ticket.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_self_healing_enabled_triggers_run(self, db):
        from app.core.config import settings
        from app.core.dex.self_healing import handle_alert

        alert = DexAlert(
            hostname="heal-host",
            alert_name="DiskFull",
            status="active",
            message="disk 92%",
        )
        db.add(alert)
        db.commit()
        db.refresh(alert)

        original = settings.dex_self_healing_enabled
        try:
            settings.dex_self_healing_enabled = True
            with patch(
                "app.core.dex.self_healing._load_remediation_map",
                return_value={
                    "DiskFull": {"action": "ansible", "playbook": "cleanup_disk"}
                },
            ), patch(
                "app.core.dex.self_healing._trigger_remediation_run",
                new=AsyncMock(return_value="run-heal-123"),
            ) as mock_run:
                result = await handle_alert(db, alert)
        finally:
            settings.dex_self_healing_enabled = original

        assert result["action"] == "remediation_started"
        assert result["run_id"] == "run-heal-123"
        assert alert.status == "remediating"
        assert alert.remediation_run_id == "run-heal-123"
        mock_run.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_remediating_alert_already_skipped(self, db):
        """Alerts already in remediating state are not re-triggered."""
        from app.core.dex.self_healing import handle_alert

        alert = DexAlert(
            hostname="skip-host",
            alert_name="DiskFull",
            status="remediating",
        )
        db.add(alert)
        db.commit()
        result = await handle_alert(db, alert)
        assert result["action"] == "skipped"


# ---------------------------------------------------------------------------
# _send_ticket_webhook
# ---------------------------------------------------------------------------


class TestSendTicketWebhook:
    @pytest.mark.asyncio
    async def test_skips_when_no_url(self):
        from app.core.config import settings
        from app.core.dex.self_healing import _send_ticket_webhook

        original = settings.dex_ticket_webhook_url
        try:
            settings.dex_ticket_webhook_url = ""
            # Should return silently without making any HTTP call
            await _send_ticket_webhook(
                DexAlert(hostname="x", alert_name="Test"), dex_score=70.0
            )
        finally:
            settings.dex_ticket_webhook_url = original

    @pytest.mark.asyncio
    async def test_posts_correct_payload(self):
        from app.core.config import settings
        from app.core.dex.self_healing import _send_ticket_webhook

        alert = DexAlert(hostname="webhook-host", alert_name="DiskFull", severity="warning")
        original = settings.dex_ticket_webhook_url
        try:
            settings.dex_ticket_webhook_url = "http://tickets.example.com/api"

            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=mock_resp)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)

            with patch(
                "app.core.dex.self_healing.httpx.AsyncClient", return_value=mock_client
            ):
                await _send_ticket_webhook(alert, dex_score=45.0)

            mock_client.post.assert_awaited_once()
            call_args = mock_client.post.call_args
            payload = call_args.kwargs.get("json") or call_args.args[1]
            assert payload["hostname"] == "webhook-host"
            assert payload["alert_name"] == "DiskFull"
            assert payload["dex_score"] == 45.0
            assert "recovery_hint" in payload
        finally:
            settings.dex_ticket_webhook_url = original
