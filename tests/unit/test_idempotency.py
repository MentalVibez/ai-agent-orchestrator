"""Unit tests for app/core/idempotency.py."""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

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


@pytest.fixture
def db():
    import app.db.database as db_module
    session = db_module.SessionLocal()
    yield session
    session.close()


# ---------------------------------------------------------------------------
# Tests: validate_idempotency_key
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestValidateIdempotencyKey:
    def test_valid_key_passes_through(self):
        from app.core.idempotency import validate_idempotency_key
        result = validate_idempotency_key("my-idempotency-key-123")
        assert result == "my-idempotency-key-123"

    def test_strips_whitespace(self):
        from app.core.idempotency import validate_idempotency_key
        result = validate_idempotency_key("  trimmed  ")
        assert result == "trimmed"

    def test_empty_key_raises(self):
        from app.core.idempotency import validate_idempotency_key
        with pytest.raises(ValueError, match="must not be empty"):
            validate_idempotency_key("")

    def test_whitespace_only_raises(self):
        from app.core.idempotency import validate_idempotency_key
        with pytest.raises(ValueError, match="must not be empty"):
            validate_idempotency_key("   ")

    def test_too_long_key_raises(self):
        from app.core.idempotency import validate_idempotency_key, MAX_KEY_LENGTH
        with pytest.raises(ValueError, match="≤"):
            validate_idempotency_key("x" * (MAX_KEY_LENGTH + 1))

    def test_key_at_max_length_is_valid(self):
        from app.core.idempotency import validate_idempotency_key, MAX_KEY_LENGTH
        key = "a" * MAX_KEY_LENGTH
        assert validate_idempotency_key(key) == key

    def test_newline_in_key_raises(self):
        from app.core.idempotency import validate_idempotency_key
        with pytest.raises(ValueError, match="printable ASCII"):
            validate_idempotency_key("key\ninjection")

    def test_carriage_return_raises(self):
        from app.core.idempotency import validate_idempotency_key
        with pytest.raises(ValueError, match="printable ASCII"):
            validate_idempotency_key("key\rinjection")

    def test_uuid_format_is_valid(self):
        from app.core.idempotency import validate_idempotency_key
        import uuid
        key = str(uuid.uuid4())
        assert validate_idempotency_key(key) == key


# ---------------------------------------------------------------------------
# Tests: store and retrieve idempotency records
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestStoreAndRetrieve:
    def test_get_existing_returns_none_for_unknown_key(self, db):
        from app.core.idempotency import get_existing_run_id
        result = get_existing_run_id(db, "unknown-key-xyz")
        assert result is None

    def test_store_then_get_returns_run_id(self, db):
        from app.core.idempotency import get_existing_run_id, store_idempotency_key
        key = "test-store-retrieve-001"
        run_id = "run-abc-123"
        stored = store_idempotency_key(db, key, run_id)
        assert stored is True
        retrieved = get_existing_run_id(db, key)
        assert retrieved == run_id

    def test_duplicate_key_store_returns_false(self, db):
        from app.core.idempotency import store_idempotency_key
        key = "test-duplicate-002"
        store_idempotency_key(db, key, "run-first")
        result = store_idempotency_key(db, key, "run-second")
        assert result is False

    def test_duplicate_key_does_not_overwrite_original(self, db):
        from app.core.idempotency import get_existing_run_id, store_idempotency_key
        key = "test-no-overwrite-003"
        store_idempotency_key(db, key, "run-original")
        store_idempotency_key(db, key, "run-attempt-2")
        retrieved = get_existing_run_id(db, key)
        assert retrieved == "run-original"

    def test_different_keys_are_independent(self, db):
        from app.core.idempotency import get_existing_run_id, store_idempotency_key
        store_idempotency_key(db, "key-A-004", "run-A")
        store_idempotency_key(db, "key-B-004", "run-B")
        assert get_existing_run_id(db, "key-A-004") == "run-A"
        assert get_existing_run_id(db, "key-B-004") == "run-B"
