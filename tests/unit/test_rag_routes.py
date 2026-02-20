"""Unit tests for app/api/v1/routes/rag.py — RAG API endpoints."""

from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.config import settings
from app.db.database import init_db
from app.main import app


# ---------------------------------------------------------------------------
# Module-level DB patch (prevents "unable to open database file" on Windows)
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True, scope="module")
def use_in_memory_db():
    """Redirect all DB calls to an in-memory SQLite DB for this test module."""
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


# ---------------------------------------------------------------------------
# Test fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def auth_disabled():
    """Disable API key requirement for tests."""
    original_require = settings.require_api_key
    original_key = settings.api_key
    settings.require_api_key = False
    settings.api_key = None
    yield
    settings.require_api_key = original_require
    settings.api_key = original_key


@pytest.fixture
def mock_rag():
    """Return a mock RAGManager."""
    rag = MagicMock()
    rag.search.return_value = []
    return rag


@pytest.fixture
def client(auth_disabled, mock_rag):
    """TestClient with auth disabled and _get_rag patched."""
    with patch("app.api.v1.routes.rag._get_rag", return_value=mock_rag):
        with TestClient(app) as c:
            yield c, mock_rag


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestIndexDocument:
    """Tests for POST /api/v1/rag/index."""

    def test_returns_204_on_success(self, client):
        tc, rag = client
        payload = {
            "collection": "col1",
            "document_id": "doc-1",
            "text": "Hello world",
            "metadata": {"source": "test"},
        }
        response = tc.post("/api/v1/rag/index", json=payload)
        assert response.status_code == 204
        rag.index_document.assert_called_once_with(
            collection_name="col1",
            document_id="doc-1",
            text="Hello world",
            metadata={"source": "test"},
        )

    def test_returns_500_on_exception(self, client):
        tc, rag = client
        rag.index_document.side_effect = RuntimeError("db error")
        response = tc.post(
            "/api/v1/rag/index",
            json={"collection": "col1", "document_id": "doc-2", "text": "text"},
        )
        assert response.status_code == 500


@pytest.mark.unit
class TestSearchDocuments:
    """Tests for POST /api/v1/rag/search."""

    def test_returns_results(self, client):
        tc, rag = client
        rag.search.return_value = [
            {"id": "doc-1", "document": "text", "metadata": {"k": "v"}, "distance": 0.1}
        ]
        response = tc.post("/api/v1/rag/search", json={"collection": "col1", "query": "hello"})
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["id"] == "doc-1"
        assert data[0]["distance"] == pytest.approx(0.1)

    def test_returns_500_on_exception(self, client):
        tc, rag = client
        rag.search.side_effect = RuntimeError("search error")
        response = tc.post("/api/v1/rag/search", json={"collection": "col1", "query": "hello"})
        assert response.status_code == 500


@pytest.mark.unit
class TestDeleteCollection:
    """Tests for DELETE /api/v1/rag/collection/{collection_name}."""

    def test_returns_204_on_success(self, client):
        tc, rag = client
        response = tc.delete("/api/v1/rag/collection/my-col")
        assert response.status_code == 204
        rag.delete_collection.assert_called_once_with("my-col")

    def test_returns_500_on_exception(self, client):
        tc, rag = client
        rag.delete_collection.side_effect = RuntimeError("delete error")
        response = tc.delete("/api/v1/rag/collection/my-col")
        assert response.status_code == 500


@pytest.mark.unit
class TestListCollections:
    """Tests for GET /api/v1/rag/collections."""

    def test_returns_list_of_collections(self, client):
        tc, rag = client
        rag.list_collections.return_value = ["col1", "col2"]
        response = tc.get("/api/v1/rag/collections")
        assert response.status_code == 200
        assert response.json() == ["col1", "col2"]

    def test_returns_500_on_exception(self, client):
        tc, rag = client
        rag.list_collections.side_effect = RuntimeError("list error")
        response = tc.get("/api/v1/rag/collections")
        assert response.status_code == 500


@pytest.mark.unit
class TestRagUnavailable:
    """Tests for when ChromaDB is not installed (503 path)."""

    def test_returns_503_when_chromadb_missing(self, auth_disabled):
        from fastapi import HTTPException, status

        def _get_rag_503():
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="RAG unavailable: No module named 'chromadb'",
            )

        with patch("app.api.v1.routes.rag._get_rag", side_effect=_get_rag_503):
            with TestClient(app) as tc:
                response = tc.post(
                    "/api/v1/rag/index",
                    json={"collection": "c", "document_id": "d", "text": "t"},
                )
        assert response.status_code == 503
        assert "RAG unavailable" in response.json()["detail"]
