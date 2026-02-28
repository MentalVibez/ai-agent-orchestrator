"""Unit tests for DEX endpoint registry (app/core/dex/endpoint_registry.py)."""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.database import init_db
from app.db.models import Endpoint

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


# ---------------------------------------------------------------------------
# create_endpoint
# ---------------------------------------------------------------------------


class TestCreateEndpoint:
    def test_creates_with_defaults(self, db):
        from app.core.dex.endpoint_registry import create_endpoint

        ep = create_endpoint(db, "create-host-1")
        assert ep.id is not None
        assert ep.hostname == "create-host-1"
        assert ep.is_active is True
        assert ep.criticality_tier == 2  # default

    def test_creates_with_all_fields(self, db):
        from app.core.dex.endpoint_registry import create_endpoint

        ep = create_endpoint(
            db,
            hostname="full-host",
            ip_address="10.0.0.1",
            owner_email="owner@example.com",
            persona="developer",
            criticality_tier=1,
            os_platform="linux",
            tags={"dept": "engineering"},
        )
        assert ep.ip_address == "10.0.0.1"
        assert ep.owner_email == "owner@example.com"
        assert ep.persona == "developer"
        assert ep.criticality_tier == 1
        assert ep.os_platform == "linux"
        assert ep.tags == {"dept": "engineering"}

    def test_duplicate_hostname_raises(self, db):
        from app.core.dex.endpoint_registry import create_endpoint

        create_endpoint(db, "dup-reg-host")
        with pytest.raises(ValueError, match="already registered"):
            create_endpoint(db, "dup-reg-host")

    def test_persisted_to_db(self, db):
        from app.core.dex.endpoint_registry import create_endpoint

        ep = create_endpoint(db, "persist-reg-host")
        fetched = db.query(Endpoint).filter_by(id=ep.id).first()
        assert fetched is not None
        assert fetched.hostname == "persist-reg-host"


# ---------------------------------------------------------------------------
# get_endpoint
# ---------------------------------------------------------------------------


class TestGetEndpoint:
    def test_returns_existing(self, db):
        from app.core.dex.endpoint_registry import create_endpoint, get_endpoint

        create_endpoint(db, "get-host-1")
        result = get_endpoint(db, "get-host-1")
        assert result is not None
        assert result.hostname == "get-host-1"

    def test_returns_none_for_unknown(self, db):
        from app.core.dex.endpoint_registry import get_endpoint

        assert get_endpoint(db, "no-such-host-xyz") is None

    def test_returns_inactive_endpoint(self, db):
        """get_endpoint returns any endpoint regardless of is_active status."""
        from app.core.dex.endpoint_registry import (
            create_endpoint,
            deregister_endpoint,
            get_endpoint,
        )

        create_endpoint(db, "inactive-get-host")
        deregister_endpoint(db, "inactive-get-host")
        result = get_endpoint(db, "inactive-get-host")
        assert result is not None
        assert result.is_active is False


# ---------------------------------------------------------------------------
# list_endpoints
# ---------------------------------------------------------------------------


class TestListEndpoints:
    def test_lists_active_by_default(self, db):
        from app.core.dex.endpoint_registry import (
            create_endpoint,
            deregister_endpoint,
            list_endpoints,
        )

        create_endpoint(db, "list-active-1")
        create_endpoint(db, "list-active-2")
        create_endpoint(db, "list-inactive-1")
        deregister_endpoint(db, "list-inactive-1")

        results = list_endpoints(db, active_only=True)
        hostnames = [e.hostname for e in results]
        assert "list-active-1" in hostnames
        assert "list-active-2" in hostnames
        assert "list-inactive-1" not in hostnames

    def test_lists_all_when_active_only_false(self, db):
        from app.core.dex.endpoint_registry import (
            create_endpoint,
            deregister_endpoint,
            list_endpoints,
        )

        create_endpoint(db, "all-active-host")
        create_endpoint(db, "all-inactive-host")
        deregister_endpoint(db, "all-inactive-host")

        results = list_endpoints(db, active_only=False)
        hostnames = [e.hostname for e in results]
        assert "all-active-host" in hostnames
        assert "all-inactive-host" in hostnames

    def test_filters_by_persona(self, db):
        from app.core.dex.endpoint_registry import create_endpoint, list_endpoints

        create_endpoint(db, "dev-persona-host", persona="developer")
        create_endpoint(db, "sales-persona-host", persona="salesperson")

        devs = list_endpoints(db, persona="developer")
        dev_hosts = [e.hostname for e in devs]
        assert "dev-persona-host" in dev_hosts
        assert "sales-persona-host" not in dev_hosts

    def test_filters_by_criticality_tier(self, db):
        from app.core.dex.endpoint_registry import create_endpoint, list_endpoints

        create_endpoint(db, "tier1-host", criticality_tier=1)
        create_endpoint(db, "tier3-host", criticality_tier=3)

        tier1 = list_endpoints(db, criticality_tier=1)
        tier1_hosts = [e.hostname for e in tier1]
        assert "tier1-host" in tier1_hosts
        assert "tier3-host" not in tier1_hosts

    def test_returns_ordered_by_hostname(self, db):
        from app.core.dex.endpoint_registry import create_endpoint, list_endpoints

        create_endpoint(db, "zzz-sort-host")
        create_endpoint(db, "aaa-sort-host")

        results = list_endpoints(db, active_only=False)
        hostnames = [e.hostname for e in results]
        # aaa should come before zzz
        aaa_idx = next(i for i, h in enumerate(hostnames) if h == "aaa-sort-host")
        zzz_idx = next(i for i, h in enumerate(hostnames) if h == "zzz-sort-host")
        assert aaa_idx < zzz_idx


# ---------------------------------------------------------------------------
# update_endpoint
# ---------------------------------------------------------------------------


class TestUpdateEndpoint:
    def test_updates_fields(self, db):
        from app.core.dex.endpoint_registry import create_endpoint, update_endpoint

        create_endpoint(db, "update-host-1")
        updated = update_endpoint(
            db,
            "update-host-1",
            owner_email="new@example.com",
            persona="executive",
            criticality_tier=1,
        )
        assert updated is not None
        assert updated.owner_email == "new@example.com"
        assert updated.persona == "executive"
        assert updated.criticality_tier == 1

    def test_partial_update_leaves_other_fields(self, db):
        from app.core.dex.endpoint_registry import create_endpoint, update_endpoint

        create_endpoint(db, "partial-update-host", persona="developer", criticality_tier=2)
        updated = update_endpoint(db, "partial-update-host", owner_email="x@x.com")
        assert updated.persona == "developer"  # unchanged
        assert updated.criticality_tier == 2  # unchanged
        assert updated.owner_email == "x@x.com"  # updated

    def test_returns_none_for_unknown(self, db):
        from app.core.dex.endpoint_registry import update_endpoint

        result = update_endpoint(db, "ghost-update-host", owner_email="x@x.com")
        assert result is None

    def test_can_reactivate_endpoint(self, db):
        from app.core.dex.endpoint_registry import (
            create_endpoint,
            deregister_endpoint,
            update_endpoint,
        )

        create_endpoint(db, "reactivate-host")
        deregister_endpoint(db, "reactivate-host")
        result = update_endpoint(db, "reactivate-host", is_active=True)
        assert result is not None
        assert result.is_active is True


# ---------------------------------------------------------------------------
# deregister_endpoint
# ---------------------------------------------------------------------------


class TestDeregisterEndpoint:
    def test_soft_deletes_endpoint(self, db):
        from app.core.dex.endpoint_registry import (
            create_endpoint,
            deregister_endpoint,
            get_endpoint,
        )

        create_endpoint(db, "deregister-host-1")
        result = deregister_endpoint(db, "deregister-host-1")
        assert result is True
        ep = get_endpoint(db, "deregister-host-1")
        assert ep is not None
        assert ep.is_active is False

    def test_returns_false_for_unknown(self, db):
        from app.core.dex.endpoint_registry import deregister_endpoint

        assert deregister_endpoint(db, "no-such-host-deregister") is False


# ---------------------------------------------------------------------------
# touch_last_scanned
# ---------------------------------------------------------------------------


class TestTouchLastScanned:
    def test_updates_timestamp(self, db):
        from app.core.dex.endpoint_registry import create_endpoint, get_endpoint, touch_last_scanned

        create_endpoint(db, "touch-host-1")
        assert get_endpoint(db, "touch-host-1").last_scanned_at is None
        touch_last_scanned(db, "touch-host-1")
        assert get_endpoint(db, "touch-host-1").last_scanned_at is not None

    def test_silently_ignores_unknown_hostname(self, db):
        from app.core.dex.endpoint_registry import touch_last_scanned

        # Should not raise
        touch_last_scanned(db, "ghost-touch-host")
