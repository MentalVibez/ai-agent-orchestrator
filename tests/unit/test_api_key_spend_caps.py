"""Unit tests for per-API-key monthly LLM spend caps.

Tests:
- create_api_key() stores max_monthly_cost_usd correctly
- get_monthly_spend_for_key() sums cost_records for the right month/key
- Planner loop enforces the cap (aborts the run when over budget)
- CreateKeyRequest API validation (ge=0)
- KeyInfoResponse includes max_monthly_cost_usd
"""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

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
    import app.db.database as db_module

    original_engine = db_module.engine
    original_session = db_module.SessionLocal

    new_engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    new_session = sessionmaker(autocommit=False, autoflush=False, bind=new_engine)

    db_module.engine = new_engine
    db_module.SessionLocal = new_session
    init_db()

    yield new_session

    db_module.engine = original_engine
    db_module.SessionLocal = original_session


# ---------------------------------------------------------------------------
# Tests: create_api_key with spend cap
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestCreateApiKeySpendCap:
    def test_cap_stored_when_provided(self, use_in_memory_db):
        from app.core.api_keys import create_api_key

        db = use_in_memory_db()
        try:
            key_id, raw_key, record = create_api_key(
                db, name="capped-key", role="operator", max_monthly_cost_usd=10.0
            )
            assert record.max_monthly_cost_usd == 10.0
        finally:
            db.close()

    def test_cap_is_none_by_default(self, use_in_memory_db):
        from app.core.api_keys import create_api_key

        db = use_in_memory_db()
        try:
            _, _, record = create_api_key(db, name="uncapped-key", role="operator")
            assert record.max_monthly_cost_usd is None
        finally:
            db.close()

    def test_cap_zero_is_stored(self, use_in_memory_db):
        from app.core.api_keys import create_api_key

        db = use_in_memory_db()
        try:
            _, _, record = create_api_key(
                db, name="zero-cap-key", role="viewer", max_monthly_cost_usd=0.0
            )
            assert record.max_monthly_cost_usd == 0.0
        finally:
            db.close()

    def test_to_dict_includes_cap(self, use_in_memory_db):
        from app.core.api_keys import create_api_key

        db = use_in_memory_db()
        try:
            _, _, record = create_api_key(
                db, name="dict-cap-key", role="admin", max_monthly_cost_usd=50.0
            )
            d = record.to_dict()
            assert "max_monthly_cost_usd" in d
            assert d["max_monthly_cost_usd"] == 50.0
        finally:
            db.close()


# ---------------------------------------------------------------------------
# Tests: get_monthly_spend_for_key
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGetMonthlySpendForKey:
    def _seed_cost_records(self, session_factory, key_id: str, month: int, costs: list):
        """Insert CostRecordDB rows for testing."""
        from app.db.models import CostRecordDB

        db = session_factory()
        try:
            for cost in costs:
                db.add(
                    CostRecordDB(
                        run_id="run-test",
                        provider="bedrock",
                        model="claude-3-haiku",
                        input_tokens=100,
                        output_tokens=50,
                        total_tokens=150,
                        cost_usd=cost,
                        api_key_id=key_id,
                        timestamp=datetime(2026, month, 1, tzinfo=None),
                    )
                )
            db.commit()
        finally:
            db.close()

    def test_sums_costs_for_correct_month(self, use_in_memory_db):
        from app.core.api_keys import get_monthly_spend_for_key

        key_id = "kid_spend_test_001"
        self._seed_cost_records(use_in_memory_db, key_id, month=3, costs=[1.0, 2.5, 0.5])

        db = use_in_memory_db()
        try:
            total = get_monthly_spend_for_key(db, key_id, year=2026, month=3)
        finally:
            db.close()

        assert abs(total - 4.0) < 1e-9

    def test_returns_zero_when_no_records(self, use_in_memory_db):
        from app.core.api_keys import get_monthly_spend_for_key

        db = use_in_memory_db()
        try:
            total = get_monthly_spend_for_key(db, "kid_nonexistent", year=2026, month=3)
        finally:
            db.close()

        assert total == 0.0

    def test_ignores_other_months(self, use_in_memory_db):
        from app.core.api_keys import get_monthly_spend_for_key

        key_id = "kid_spend_test_002"
        self._seed_cost_records(use_in_memory_db, key_id, month=2, costs=[99.0])

        db = use_in_memory_db()
        try:
            # Querying March should return 0 even though Feb has records
            total = get_monthly_spend_for_key(db, key_id, year=2026, month=3)
        finally:
            db.close()

        assert total == 0.0

    def test_ignores_other_keys(self, use_in_memory_db):
        from app.core.api_keys import get_monthly_spend_for_key

        key_a = "kid_spend_key_a"
        key_b = "kid_spend_key_b"
        self._seed_cost_records(use_in_memory_db, key_a, month=3, costs=[5.0])
        self._seed_cost_records(use_in_memory_db, key_b, month=3, costs=[100.0])

        db = use_in_memory_db()
        try:
            total_a = get_monthly_spend_for_key(db, key_a, year=2026, month=3)
        finally:
            db.close()

        assert abs(total_a - 5.0) < 1e-9


# ---------------------------------------------------------------------------
# Tests: planner loop per-key cap enforcement
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestPlannerPerKeyCap:
    @pytest.mark.asyncio
    async def test_run_aborted_when_monthly_cap_exceeded(self, use_in_memory_db):
        """Planner should abort with status=failed when monthly cap is exceeded."""
        from app.core.api_keys import create_api_key
        from app.db.models import CostRecordDB

        # Create a key with $1 monthly cap
        db = use_in_memory_db()
        try:
            _, _, key_record = create_api_key(
                db, name="cap-test-key", role="operator", max_monthly_cost_usd=1.0
            )
            key_id = key_record.key_id

            # Seed a cost record that already puts us at $1.50 (over the $1 cap)
            db.add(
                CostRecordDB(
                    run_id="prior-run",
                    provider="bedrock",
                    model="claude-3-haiku",
                    input_tokens=100,
                    output_tokens=50,
                    total_tokens=150,
                    cost_usd=1.50,
                    api_key_id=key_id,
                    timestamp=datetime.now(timezone.utc).replace(tzinfo=None),
                )
            )
            db.commit()
        finally:
            db.close()

        captured_updates = []

        async def mock_update_run(run_id, **kwargs):
            captured_updates.append(kwargs)

        async def mock_get_run(run_id):
            mock = MagicMock()
            mock.status = "running"
            return mock

        async def mock_append_event(run_id, event_type, payload):
            pass

        with patch("app.planner.loop.update_run", mock_update_run), \
             patch("app.planner.loop.get_run_by_id", mock_get_run), \
             patch("app.planner.loop.append_run_event", mock_append_event), \
             patch("app.db.database.SessionLocal", use_in_memory_db):
            from app.planner.loop import _run_planner_steps

            await _run_planner_steps(
                run_id="test-run-cap",
                goal_for_prompt="test goal",
                role_prompt="You are a helpful assistant.",
                tools_text="No tools.",
                tools=[],
                filter_enabled=False,
                llm_generate=AsyncMock(return_value='{"action": "finish", "answer": "done"}'),
                llm_timeout=0,
                steps=[],
                tool_calls_records=[],
                conversation=[],
                mcp_manager=MagicMock(),
                api_key_id=key_id,
            )

        # Should have called update_run with status=failed and a budget cap message
        assert any(
            u.get("status") == "failed" and "budget cap" in (u.get("error") or "").lower()
            for u in captured_updates
        )

    @pytest.mark.asyncio
    async def test_run_proceeds_when_no_cap_set(self, use_in_memory_db):
        """Planner should not abort when key has no monthly cap."""
        from app.core.api_keys import create_api_key

        db = use_in_memory_db()
        try:
            _, _, key_record = create_api_key(
                db, name="no-cap-key", role="operator"  # no max_monthly_cost_usd
            )
            key_id = key_record.key_id
        finally:
            db.close()

        finish_response = '{"action": "finish", "answer": "all good"}'
        updates = []

        async def mock_update_run(run_id, **kwargs):
            updates.append(kwargs)

        async def mock_get_run(run_id):
            mock = MagicMock()
            mock.status = "running"
            return mock

        async def mock_append_event(run_id, event_type, payload):
            pass

        with patch("app.planner.loop.update_run", mock_update_run), \
             patch("app.planner.loop.get_run_by_id", mock_get_run), \
             patch("app.planner.loop.append_run_event", mock_append_event), \
             patch("app.db.database.SessionLocal", use_in_memory_db):
            from app.planner.loop import _run_planner_steps

            await _run_planner_steps(
                run_id="test-run-nocap",
                goal_for_prompt="test goal",
                role_prompt="You are a helpful assistant.",
                tools_text="No tools.",
                tools=[],
                filter_enabled=False,
                llm_generate=AsyncMock(return_value=finish_response),
                llm_timeout=0,
                steps=[],
                tool_calls_records=[],
                conversation=[],
                mcp_manager=MagicMock(),
                api_key_id=key_id,
            )

        # Should have completed (not failed)
        assert any(u.get("status") == "completed" for u in updates)
        assert not any(
            u.get("status") == "failed" and "budget cap" in (u.get("error") or "").lower()
            for u in updates
        )


# ---------------------------------------------------------------------------
# Tests: API route request/response models
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestApiKeyRouteModels:
    def test_create_request_accepts_cap(self):
        from app.api.v1.routes.api_keys import CreateKeyRequest

        req = CreateKeyRequest(name="test", role="operator", max_monthly_cost_usd=25.0)
        assert req.max_monthly_cost_usd == 25.0

    def test_create_request_cap_defaults_to_none(self):
        from app.api.v1.routes.api_keys import CreateKeyRequest

        req = CreateKeyRequest(name="test", role="operator")
        assert req.max_monthly_cost_usd is None

    def test_create_request_rejects_negative_cap(self):
        import pydantic

        from app.api.v1.routes.api_keys import CreateKeyRequest

        with pytest.raises(pydantic.ValidationError):
            CreateKeyRequest(name="test", role="operator", max_monthly_cost_usd=-1.0)

    def test_key_info_response_has_cap_field(self):
        from app.api.v1.routes.api_keys import KeyInfoResponse

        resp = KeyInfoResponse(
            key_id="kid_abc",
            name="test",
            role="operator",
            is_active=True,
            created_at=None,
            last_used_at=None,
            revoked_at=None,
            max_monthly_cost_usd=42.0,
        )
        assert resp.max_monthly_cost_usd == 42.0

