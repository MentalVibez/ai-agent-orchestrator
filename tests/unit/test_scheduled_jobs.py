"""Unit tests for DEX scheduled arq jobs (app/core/dex/scheduled_jobs.py).

All imports in scheduled_jobs.py are lazy (inside function bodies), so patches
must target the source modules (e.g. app.core.dex.endpoint_registry.list_endpoints)
rather than the scheduled_jobs module namespace.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.database import init_db

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


def _make_http_response(status_code: int, json_data: dict) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_data
    return resp


def _make_async_http_client(post_resp=None, get_resp=None, post_side_effect=None):
    """Build a mock async httpx client context manager."""
    mock_client = AsyncMock()
    if post_side_effect:
        mock_client.post = AsyncMock(side_effect=post_side_effect)
    else:
        mock_client.post = AsyncMock(return_value=post_resp)
    if get_resp is not None:
        mock_client.get = AsyncMock(return_value=get_resp)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    return mock_client


# ---------------------------------------------------------------------------
# dex_scan_all_endpoints
# ---------------------------------------------------------------------------


class TestDexScanAllEndpoints:
    @pytest.mark.asyncio
    async def test_no_endpoints_returns_zero(self):
        from app.core.dex.scheduled_jobs import dex_scan_all_endpoints

        with patch(
            "app.core.dex.endpoint_registry.list_endpoints", return_value=[]
        ):
            result = await dex_scan_all_endpoints(ctx={})

        assert result == {"scanned": 0}

    @pytest.mark.asyncio
    async def test_scan_http_error_increments_errors(self):
        from app.core.dex.scheduled_jobs import dex_scan_all_endpoints

        endpoint = MagicMock()
        endpoint.hostname = "error-host"

        mock_client = _make_async_http_client(
            post_resp=_make_http_response(500, {})
        )

        with patch(
            "app.core.dex.endpoint_registry.list_endpoints", return_value=[endpoint]
        ), patch("httpx.AsyncClient", return_value=mock_client):
            result = await dex_scan_all_endpoints(ctx={})

        assert result["errors"] == 1
        assert result["scanned"] == 0

    @pytest.mark.asyncio
    async def test_scan_missing_run_id_increments_errors(self):
        from app.core.dex.scheduled_jobs import dex_scan_all_endpoints

        endpoint = MagicMock()
        endpoint.hostname = "no-run-id-host"

        mock_client = _make_async_http_client(
            post_resp=_make_http_response(200, {})  # no run_id key
        )

        with patch(
            "app.core.dex.endpoint_registry.list_endpoints", return_value=[endpoint]
        ), patch("httpx.AsyncClient", return_value=mock_client):
            result = await dex_scan_all_endpoints(ctx={})

        assert result["errors"] == 1

    @pytest.mark.asyncio
    async def test_scan_run_completes_and_processes(self):
        from app.core.dex.scheduled_jobs import dex_scan_all_endpoints

        endpoint = MagicMock()
        endpoint.hostname = "complete-host"

        scan_resp = _make_http_response(200, {"run_id": "run-complete-1"})
        poll_resp = _make_http_response(200, {"status": "completed", "answer": '{"cpu_pct": 20}'})
        mock_client = _make_async_http_client(post_resp=scan_resp, get_resp=poll_resp)

        with patch(
            "app.core.dex.endpoint_registry.list_endpoints", return_value=[endpoint]
        ), patch(
            "httpx.AsyncClient", return_value=mock_client
        ), patch(
            "app.core.dex.telemetry_collector.process_completed_scan"
        ) as mock_process:
            result = await dex_scan_all_endpoints(ctx={})

        assert result["scanned"] == 1
        assert result["errors"] == 0
        mock_process.assert_called_once()

    @pytest.mark.asyncio
    async def test_scan_run_fails_increments_skipped(self):
        from app.core.dex.scheduled_jobs import dex_scan_all_endpoints

        endpoint = MagicMock()
        endpoint.hostname = "failed-run-host"

        scan_resp = _make_http_response(200, {"run_id": "run-fail-1"})
        poll_resp = _make_http_response(200, {"status": "failed", "answer": ""})
        mock_client = _make_async_http_client(post_resp=scan_resp, get_resp=poll_resp)

        with patch(
            "app.core.dex.endpoint_registry.list_endpoints", return_value=[endpoint]
        ), patch("httpx.AsyncClient", return_value=mock_client):
            result = await dex_scan_all_endpoints(ctx={})

        assert result["skipped"] == 1
        assert result["scanned"] == 0

    @pytest.mark.asyncio
    async def test_scan_exception_increments_errors(self):
        from app.core.dex.scheduled_jobs import dex_scan_all_endpoints

        endpoint = MagicMock()
        endpoint.hostname = "exception-host"

        mock_client = _make_async_http_client(
            post_side_effect=ConnectionError("refused")
        )

        with patch(
            "app.core.dex.endpoint_registry.list_endpoints", return_value=[endpoint]
        ), patch("httpx.AsyncClient", return_value=mock_client):
            result = await dex_scan_all_endpoints(ctx={})

        assert result["errors"] == 1


# ---------------------------------------------------------------------------
# dex_check_predictive_alerts
# ---------------------------------------------------------------------------


class TestDexCheckPredictiveAlerts:
    @pytest.mark.asyncio
    async def test_no_endpoints_returns_zero(self):
        from app.core.dex.scheduled_jobs import dex_check_predictive_alerts

        with patch(
            "app.core.dex.endpoint_registry.list_endpoints", return_value=[]
        ):
            result = await dex_check_predictive_alerts(ctx={})

        assert result["endpoints_analyzed"] == 0
        assert result["alerts_created_or_updated"] == 0

    @pytest.mark.asyncio
    async def test_counts_alert_trends(self):
        from app.core.dex.scheduled_jobs import dex_check_predictive_alerts

        ep1 = MagicMock()
        ep1.hostname = "trend-host-1"
        ep2 = MagicMock()
        ep2.hostname = "trend-host-2"

        def fake_analyze(db, hostname):
            if hostname == "trend-host-1":
                return [{"metric": "disk_pct", "status": "alert"}]
            return [{"metric": "disk_pct", "status": "stable"}]

        with patch(
            "app.core.dex.endpoint_registry.list_endpoints", return_value=[ep1, ep2]
        ), patch(
            "app.core.dex.predictive_analysis.analyze_trends", side_effect=fake_analyze
        ):
            result = await dex_check_predictive_alerts(ctx={})

        assert result["endpoints_analyzed"] == 2
        assert result["alerts_created_or_updated"] == 1

    @pytest.mark.asyncio
    async def test_per_endpoint_exception_continues(self):
        from app.core.dex.scheduled_jobs import dex_check_predictive_alerts

        ep1 = MagicMock()
        ep1.hostname = "broken-host"
        ep2 = MagicMock()
        ep2.hostname = "ok-host"

        def fake_analyze(db, hostname):
            if hostname == "broken-host":
                raise RuntimeError("analysis failed")
            return []

        with patch(
            "app.core.dex.endpoint_registry.list_endpoints", return_value=[ep1, ep2]
        ), patch(
            "app.core.dex.predictive_analysis.analyze_trends", side_effect=fake_analyze
        ):
            # Must not raise — per-endpoint errors are caught and logged
            result = await dex_check_predictive_alerts(ctx={})

        assert result["endpoints_analyzed"] == 2
