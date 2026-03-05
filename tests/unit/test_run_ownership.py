"""Unit tests for Run row-level security (ownership scoping).

Tests:
- create_run() stores api_key_id on the Run record
- list_runs() scoped by api_key_id returns only caller's runs
- admin list_runs() (no api_key_id filter) returns all runs
- GET /runs/{run_id} returns 403 when caller doesn't own the run
- GET /runs/{run_id} returns 200 for admin regardless of ownership
"""

from unittest.mock import MagicMock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.database import init_db

# ---------------------------------------------------------------------------
# In-memory DB fixture (module-scoped)
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True, scope="module")
def use_in_memory_db():
    import app.core.run_store as run_store_module
    import app.db.database as db_module

    original_engine = db_module.engine
    original_session = db_module.SessionLocal
    original_rs_session = run_store_module.SessionLocal

    new_engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    new_session = sessionmaker(autocommit=False, autoflush=False, bind=new_engine)

    db_module.engine = new_engine
    db_module.SessionLocal = new_session
    run_store_module.SessionLocal = new_session
    init_db()

    yield new_session

    db_module.engine = original_engine
    db_module.SessionLocal = original_session
    run_store_module.SessionLocal = original_rs_session


# ---------------------------------------------------------------------------
# Tests: create_run stores api_key_id
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestCreateRunOwnership:
    @pytest.mark.asyncio
    async def test_create_run_stores_api_key_id(self):
        from app.core.run_store import create_run

        run = await create_run(
            goal="test ownership",
            agent_profile_id="default",
            api_key_id="kid_owner_001",
        )
        assert run.api_key_id == "kid_owner_001"

    @pytest.mark.asyncio
    async def test_create_run_no_key_is_null(self):
        from app.core.run_store import create_run

        run = await create_run(goal="unowned run", agent_profile_id="default")
        assert run.api_key_id is None


# ---------------------------------------------------------------------------
# Tests: list_runs scoping
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestListRunsScoping:
    @pytest.mark.asyncio
    async def test_list_scoped_to_caller(self):
        from app.core.run_store import create_run, list_runs

        key_a = "kid_scope_a"
        key_b = "kid_scope_b"
        await create_run(goal="run for A", agent_profile_id="default", api_key_id=key_a)
        await create_run(goal="run for B", agent_profile_id="default", api_key_id=key_b)

        runs_a = await list_runs(api_key_id=key_a)
        ids_a = {r.api_key_id for r in runs_a}
        assert key_b not in ids_a
        assert key_a in ids_a

    @pytest.mark.asyncio
    async def test_admin_sees_all_runs(self):
        from app.core.run_store import create_run, list_runs

        key_x = "kid_admin_see_x"
        key_y = "kid_admin_see_y"
        await create_run(goal="run X", agent_profile_id="default", api_key_id=key_x)
        await create_run(goal="run Y", agent_profile_id="default", api_key_id=key_y)

        # No api_key_id filter → admin sees all
        all_runs = await list_runs(limit=100)
        all_key_ids = {r.api_key_id for r in all_runs}
        assert key_x in all_key_ids
        assert key_y in all_key_ids


# ---------------------------------------------------------------------------
# Tests: route-level ownership enforcement (GET /runs/{run_id})
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestRunRouteOwnership:
    @pytest.mark.asyncio
    async def test_get_run_403_for_different_key(self, use_in_memory_db):
        """Non-admin caller should get 403 when fetching a run owned by another key."""
        from app.core.run_store import create_run

        run = await create_run(
            goal="owned run",
            agent_profile_id="default",
            api_key_id="kid_real_owner",
        )

        # Simulate a request from a different key
        fake_request = MagicMock()
        fake_request.state.api_key_role = "operator"
        fake_request.state.api_key_id = "kid_other_caller"

        from fastapi import HTTPException

        from app.api.v1.routes.runs import _check_run_ownership

        with pytest.raises(HTTPException) as exc_info:
            _check_run_ownership(fake_request, run)
        assert exc_info.value.status_code == 403

    @pytest.mark.asyncio
    async def test_get_run_200_for_admin(self, use_in_memory_db):
        """Admin should never get a 403 regardless of which key owns the run."""
        from app.api.v1.routes.runs import _check_run_ownership
        from app.core.run_store import create_run

        run = await create_run(
            goal="admin test run",
            agent_profile_id="default",
            api_key_id="kid_some_operator",
        )

        fake_request = MagicMock()
        fake_request.state.api_key_role = "admin"
        fake_request.state.api_key_id = "kid_admin_key"

        # Should not raise
        _check_run_ownership(fake_request, run)

    @pytest.mark.asyncio
    async def test_get_run_200_for_owner(self, use_in_memory_db):
        """Owner should pass the ownership check."""
        from app.api.v1.routes.runs import _check_run_ownership
        from app.core.run_store import create_run

        run = await create_run(
            goal="owner check",
            agent_profile_id="default",
            api_key_id="kid_legit_owner",
        )

        fake_request = MagicMock()
        fake_request.state.api_key_role = "operator"
        fake_request.state.api_key_id = "kid_legit_owner"

        # Should not raise
        _check_run_ownership(fake_request, run)

    @pytest.mark.asyncio
    async def test_get_run_200_for_unowned_run(self, use_in_memory_db):
        """Legacy/unowned run (api_key_id=None) should be accessible by any key."""
        from app.api.v1.routes.runs import _check_run_ownership
        from app.core.run_store import create_run

        run = await create_run(goal="legacy run", agent_profile_id="default")

        fake_request = MagicMock()
        fake_request.state.api_key_role = "operator"
        fake_request.state.api_key_id = "kid_anyone"

        # Should not raise (run.api_key_id is None)
        _check_run_ownership(fake_request, run)
