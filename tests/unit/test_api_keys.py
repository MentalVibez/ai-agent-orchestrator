"""Unit tests for app/core/api_keys.py and app/api/v1/routes/api_keys.py."""

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.config import settings
from app.db.database import init_db
from app.main import app


# ---------------------------------------------------------------------------
# Module-level DB patch
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True, scope="module")
def use_in_memory_db():
    import app.api.v1.routes.api_keys as api_keys_routes_module
    import app.core.persistence as persistence_module
    import app.core.run_store as run_store_module
    import app.db.database as db_module

    original_engine = db_module.engine
    original_session = db_module.SessionLocal
    original_run_store_session = run_store_module.SessionLocal
    original_persistence_session = persistence_module.SessionLocal
    original_routes_session = api_keys_routes_module.SessionLocal

    new_engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    new_session = sessionmaker(autocommit=False, autoflush=False, bind=new_engine)

    db_module.engine = new_engine
    db_module.SessionLocal = new_session
    run_store_module.SessionLocal = new_session
    persistence_module.SessionLocal = new_session
    api_keys_routes_module.SessionLocal = new_session  # by-value import in route file

    init_db()
    yield

    db_module.engine = original_engine
    db_module.SessionLocal = original_session
    run_store_module.SessionLocal = original_run_store_session
    persistence_module.SessionLocal = original_persistence_session
    api_keys_routes_module.SessionLocal = original_routes_session


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _db():
    import app.db.database as db_module
    db = db_module.SessionLocal()
    try:
        yield db
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Tests: core api_keys module
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGenerateApiKey:
    def test_returns_tuple_of_two_strings(self):
        from app.core.api_keys import generate_api_key
        key_id, raw_key = generate_api_key()
        assert isinstance(key_id, str)
        assert isinstance(raw_key, str)

    def test_key_id_has_kid_prefix(self):
        from app.core.api_keys import generate_api_key
        key_id, _ = generate_api_key()
        assert key_id.startswith("kid_")

    def test_raw_key_has_orc_prefix(self):
        from app.core.api_keys import generate_api_key
        _, raw_key = generate_api_key()
        assert raw_key.startswith("orc_")

    def test_each_call_produces_unique_keys(self):
        from app.core.api_keys import generate_api_key
        pairs = {generate_api_key() for _ in range(10)}
        assert len(pairs) == 10


@pytest.mark.unit
class TestHashKey:
    def test_same_input_produces_same_hash(self):
        from app.core.api_keys import _hash_key
        assert _hash_key("abc") == _hash_key("abc")

    def test_different_inputs_produce_different_hashes(self):
        from app.core.api_keys import _hash_key
        assert _hash_key("abc") != _hash_key("xyz")

    def test_hash_is_64_hex_chars(self):
        from app.core.api_keys import _hash_key
        h = _hash_key("test-key")
        assert len(h) == 64
        assert all(c in "0123456789abcdef" for c in h)


@pytest.mark.unit
class TestCreateApiKey:
    def test_creates_record_in_db(self):
        from app.core.api_keys import create_api_key
        import app.db.database as db_module
        db = db_module.SessionLocal()
        try:
            key_id, raw_key, record = create_api_key(db, name="test-key", role="operator")
            assert record.key_id == key_id
            assert record.name == "test-key"
            assert record.role == "operator"
            assert record.is_active is True
        finally:
            db.close()

    def test_raw_key_not_stored_in_db(self):
        from app.core.api_keys import create_api_key, _hash_key
        import app.db.database as db_module
        db = db_module.SessionLocal()
        try:
            key_id, raw_key, record = create_api_key(db, name="no-plaintext", role="viewer")
            assert record.key_hash != raw_key
            assert record.key_hash == _hash_key(raw_key)
        finally:
            db.close()

    def test_invalid_role_raises_value_error(self):
        from app.core.api_keys import create_api_key
        import app.db.database as db_module
        db = db_module.SessionLocal()
        try:
            with pytest.raises(ValueError, match="Invalid role"):
                create_api_key(db, name="bad", role="superuser")
        finally:
            db.close()

    def test_admin_role_is_valid(self):
        from app.core.api_keys import create_api_key
        import app.db.database as db_module
        db = db_module.SessionLocal()
        try:
            _, _, record = create_api_key(db, name="admin-key", role="admin")
            assert record.role == "admin"
        finally:
            db.close()


@pytest.mark.unit
class TestLookupApiKey:
    def test_returns_record_for_correct_key(self):
        from app.core.api_keys import create_api_key, lookup_api_key
        import app.db.database as db_module
        db = db_module.SessionLocal()
        try:
            _, raw_key, _ = create_api_key(db, name="lookup-test", role="operator")
            found = lookup_api_key(db, raw_key)
            assert found is not None
            assert found.name == "lookup-test"
        finally:
            db.close()

    def test_returns_none_for_wrong_key(self):
        from app.core.api_keys import lookup_api_key
        import app.db.database as db_module
        db = db_module.SessionLocal()
        try:
            result = lookup_api_key(db, "orc_totally-wrong-key-that-does-not-exist")
            assert result is None
        finally:
            db.close()

    def test_returns_none_for_revoked_key(self):
        from app.core.api_keys import create_api_key, lookup_api_key, revoke_api_key
        import app.db.database as db_module
        db = db_module.SessionLocal()
        try:
            key_id, raw_key, _ = create_api_key(db, name="revoke-lookup", role="viewer")
            revoke_api_key(db, key_id)
            found = lookup_api_key(db, raw_key)
            assert found is None
        finally:
            db.close()

    def test_updates_last_used_at_on_match(self):
        from app.core.api_keys import create_api_key, lookup_api_key
        import app.db.database as db_module
        db = db_module.SessionLocal()
        try:
            _, raw_key, _ = create_api_key(db, name="last-used", role="operator")
            record = lookup_api_key(db, raw_key)
            assert record is not None
            assert record.last_used_at is not None
        finally:
            db.close()


@pytest.mark.unit
class TestRevokeApiKey:
    def test_sets_is_active_false(self):
        from app.core.api_keys import create_api_key, revoke_api_key
        import app.db.database as db_module
        db = db_module.SessionLocal()
        try:
            key_id, _, _ = create_api_key(db, name="to-revoke", role="operator")
            record = revoke_api_key(db, key_id)
            assert record is not None
            assert record.is_active is False
            assert record.revoked_at is not None
        finally:
            db.close()

    def test_returns_none_for_unknown_key_id(self):
        from app.core.api_keys import revoke_api_key
        import app.db.database as db_module
        db = db_module.SessionLocal()
        try:
            result = revoke_api_key(db, "kid_doesnotexist")
            assert result is None
        finally:
            db.close()


@pytest.mark.unit
class TestHasRole:
    def test_admin_satisfies_admin(self):
        from app.core.api_keys import has_role
        from app.db.models import ApiKeyRecord
        record = ApiKeyRecord(role="admin")
        assert has_role(record, "admin") is True

    def test_admin_satisfies_operator(self):
        from app.core.api_keys import has_role
        from app.db.models import ApiKeyRecord
        record = ApiKeyRecord(role="admin")
        assert has_role(record, "operator") is True

    def test_admin_satisfies_viewer(self):
        from app.core.api_keys import has_role
        from app.db.models import ApiKeyRecord
        record = ApiKeyRecord(role="admin")
        assert has_role(record, "viewer") is True

    def test_operator_fails_admin(self):
        from app.core.api_keys import has_role
        from app.db.models import ApiKeyRecord
        record = ApiKeyRecord(role="operator")
        assert has_role(record, "admin") is False

    def test_operator_satisfies_operator(self):
        from app.core.api_keys import has_role
        from app.db.models import ApiKeyRecord
        record = ApiKeyRecord(role="operator")
        assert has_role(record, "operator") is True

    def test_viewer_fails_operator(self):
        from app.core.api_keys import has_role
        from app.db.models import ApiKeyRecord
        record = ApiKeyRecord(role="viewer")
        assert has_role(record, "operator") is False

    def test_unknown_role_fails_viewer(self):
        from app.core.api_keys import has_role
        from app.db.models import ApiKeyRecord
        record = ApiKeyRecord(role="unknown_role")
        assert has_role(record, "viewer") is False


# ---------------------------------------------------------------------------
# Tests: admin routes (require admin API key via env fallback)
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def admin_client():
    """TestClient with env-var bootstrap admin key set."""
    original_require = settings.require_api_key
    original_key = settings.api_key
    settings.require_api_key = True
    settings.api_key = "test-admin-bootstrap-key"

    with TestClient(app, raise_server_exceptions=True) as c:
        yield c

    settings.require_api_key = original_require
    settings.api_key = original_key


@pytest.fixture(scope="module")
def admin_headers():
    return {"X-API-Key": "test-admin-bootstrap-key"}


@pytest.mark.unit
class TestAdminKeyRoutes:
    def test_create_key_returns_201(self, admin_client, admin_headers):
        resp = admin_client.post(
            "/api/v1/admin/keys",
            json={"name": "my-service", "role": "operator"},
            headers=admin_headers,
        )
        assert resp.status_code == 201
        data = resp.json()
        assert "raw_key" in data
        assert data["raw_key"].startswith("orc_")
        assert data["role"] == "operator"

    def test_create_key_invalid_role_returns_422(self, admin_client, admin_headers):
        resp = admin_client.post(
            "/api/v1/admin/keys",
            json={"name": "bad", "role": "superuser"},
            headers=admin_headers,
        )
        assert resp.status_code == 422

    def test_list_keys_returns_200(self, admin_client, admin_headers):
        resp = admin_client.get("/api/v1/admin/keys", headers=admin_headers)
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_revoke_unknown_key_returns_404(self, admin_client, admin_headers):
        resp = admin_client.delete(
            "/api/v1/admin/keys/kid_doesnotexist", headers=admin_headers
        )
        assert resp.status_code == 404

    def test_create_then_revoke_roundtrip(self, admin_client, admin_headers):
        create_resp = admin_client.post(
            "/api/v1/admin/keys",
            json={"name": "temp-key", "role": "viewer"},
            headers=admin_headers,
        )
        assert create_resp.status_code == 201
        key_id = create_resp.json()["key_id"]

        revoke_resp = admin_client.delete(
            f"/api/v1/admin/keys/{key_id}", headers=admin_headers
        )
        assert revoke_resp.status_code == 200
        assert revoke_resp.json()["revoked"] is True

    def test_unauthenticated_request_returns_401(self, admin_client):
        resp = admin_client.get("/api/v1/admin/keys")
        assert resp.status_code == 401

    def test_viewer_role_cannot_access_admin_routes(self, admin_client, admin_headers):
        # Create a viewer key
        create_resp = admin_client.post(
            "/api/v1/admin/keys",
            json={"name": "viewer-key", "role": "viewer"},
            headers=admin_headers,
        )
        assert create_resp.status_code == 201
        viewer_raw_key = create_resp.json()["raw_key"]

        # Try to list keys with viewer key — should get 403
        resp = admin_client.get(
            "/api/v1/admin/keys", headers={"X-API-Key": viewer_raw_key}
        )
        assert resp.status_code == 403
