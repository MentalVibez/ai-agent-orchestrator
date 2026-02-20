"""Unit tests for app/core/rag_manager.py."""

import sys
from unittest.mock import MagicMock, patch

import pytest


def _make_chromadb_mock():
    """Return a MagicMock that stands in for the chromadb module."""
    mock_chroma = MagicMock()
    mock_client = MagicMock()
    mock_chroma.PersistentClient.return_value = mock_client
    mock_chroma.Client.return_value = mock_client
    return mock_chroma, mock_client


@pytest.mark.unit
class TestGetChromadb:
    """Tests for _get_chromadb() lazy import helper."""

    def test_returns_chromadb_when_installed(self):
        """Returns the chromadb module when it is importable."""
        mock_chroma = MagicMock()
        with patch.dict("sys.modules", {"chromadb": mock_chroma}):
            from app.core.rag_manager import _get_chromadb
            result = _get_chromadb()
        assert result is mock_chroma

    def test_raises_import_error_when_not_installed(self):
        """Raises ImportError with a helpful message when chromadb is absent."""
        # Remove chromadb from sys.modules so the import fails
        saved = sys.modules.pop("chromadb", None)
        try:
            from app.core.rag_manager import _get_chromadb
            with patch.dict("sys.modules", {"chromadb": None}):
                with pytest.raises(ImportError, match="chromadb is required"):
                    _get_chromadb()
        finally:
            if saved is not None:
                sys.modules["chromadb"] = saved


@pytest.mark.unit
class TestRAGManagerInit:
    """Tests for RAGManager.__init__ and _get_client()."""

    def test_init_stores_persist_directory(self):
        """persist_directory is stored and client is not yet initialised."""
        from app.core.rag_manager import RAGManager
        rag = RAGManager(persist_directory="/tmp/chroma")
        assert rag._persist_directory == "/tmp/chroma"
        assert rag._client is None

    def test_get_client_uses_persistent_client_when_dir_set(self):
        """Creates a PersistentClient when persist_directory is provided."""
        mock_chroma, mock_client = _make_chromadb_mock()
        with patch("app.core.rag_manager._get_chromadb", return_value=mock_chroma):
            from app.core.rag_manager import RAGManager
            rag = RAGManager(persist_directory="/tmp/chroma")
            client = rag._get_client()
        mock_chroma.PersistentClient.assert_called_once_with(path="/tmp/chroma")
        assert client is mock_client

    def test_get_client_uses_ephemeral_client_when_no_dir(self):
        """Creates an ephemeral Client() when persist_directory is None."""
        mock_chroma, mock_client = _make_chromadb_mock()
        with patch("app.core.rag_manager._get_chromadb", return_value=mock_chroma):
            from app.core.rag_manager import RAGManager
            rag = RAGManager(persist_directory=None)
            client = rag._get_client()
        mock_chroma.Client.assert_called_once()
        assert client is mock_client

    def test_get_client_is_cached(self):
        """_get_client() returns the same object on repeated calls."""
        mock_chroma, mock_client = _make_chromadb_mock()
        with patch("app.core.rag_manager._get_chromadb", return_value=mock_chroma):
            from app.core.rag_manager import RAGManager
            rag = RAGManager()
            c1 = rag._get_client()
            c2 = rag._get_client()
        assert c1 is c2
        mock_chroma.Client.assert_called_once()  # not called twice


@pytest.mark.unit
class TestRAGManagerIndexDocument:
    """Tests for RAGManager.index_document()."""

    def _rag_with_mock_client(self, mock_client):
        from app.core.rag_manager import RAGManager
        rag = RAGManager()
        rag._client = mock_client
        return rag

    def test_upserts_document_to_collection(self):
        """Calls upsert on the collection with correct id, document, metadata."""
        mock_collection = MagicMock()
        mock_client = MagicMock()
        mock_client.get_or_create_collection.return_value = mock_collection

        rag = self._rag_with_mock_client(mock_client)
        rag.index_document("col1", "doc-1", "Hello world", {"source": "test"})

        mock_client.get_or_create_collection.assert_called_once_with("col1")
        mock_collection.upsert.assert_called_once_with(
            ids=["doc-1"],
            documents=["Hello world"],
            metadatas=[{"source": "test"}],
        )

    def test_converts_metadata_values_to_strings(self):
        """Non-string metadata values are cast to str before upsert."""
        mock_collection = MagicMock()
        mock_client = MagicMock()
        mock_client.get_or_create_collection.return_value = mock_collection

        rag = self._rag_with_mock_client(mock_client)
        rag.index_document("col1", "doc-2", "text", {"count": 42, "flag": True})

        call_kwargs = mock_collection.upsert.call_args.kwargs
        meta = call_kwargs["metadatas"][0]
        assert meta == {"count": "42", "flag": "True"}

    def test_no_metadata_passes_none(self):
        """When metadata is empty, metadatas=None is passed to upsert."""
        mock_collection = MagicMock()
        mock_client = MagicMock()
        mock_client.get_or_create_collection.return_value = mock_collection

        rag = self._rag_with_mock_client(mock_client)
        rag.index_document("col1", "doc-3", "text")

        call_kwargs = mock_collection.upsert.call_args.kwargs
        assert call_kwargs["metadatas"] is None


@pytest.mark.unit
class TestRAGManagerSearch:
    """Tests for RAGManager.search()."""

    def _rag_with_mock_client(self, mock_client):
        from app.core.rag_manager import RAGManager
        rag = RAGManager()
        rag._client = mock_client
        return rag

    def test_returns_formatted_results(self):
        """Formats query results into list of id/document/metadata/distance dicts."""
        mock_collection = MagicMock()
        mock_collection.count.return_value = 3
        mock_collection.query.return_value = {
            "ids": [["doc-1", "doc-2"]],
            "documents": [["text 1", "text 2"]],
            "metadatas": [[{"k": "v"}, {}]],
            "distances": [[0.1, 0.2]],
        }
        mock_client = MagicMock()
        mock_client.get_collection.return_value = mock_collection

        rag = self._rag_with_mock_client(mock_client)
        results = rag.search("col1", "query", n_results=2)

        assert len(results) == 2
        assert results[0] == {"id": "doc-1", "document": "text 1", "metadata": {"k": "v"}, "distance": 0.1}
        assert results[1] == {"id": "doc-2", "document": "text 2", "metadata": {}, "distance": 0.2}

    def test_returns_empty_list_when_collection_missing(self):
        """Returns [] when get_collection raises (collection doesn't exist)."""
        mock_client = MagicMock()
        mock_client.get_collection.side_effect = Exception("Collection not found")

        rag = self._rag_with_mock_client(mock_client)
        results = rag.search("nonexistent", "query")

        assert results == []

    def test_passes_where_filter(self):
        """where parameter is forwarded to collection.query()."""
        mock_collection = MagicMock()
        mock_collection.count.return_value = 1
        mock_collection.query.return_value = {
            "ids": [[]], "documents": [[]], "metadatas": [[]], "distances": [[]]
        }
        mock_client = MagicMock()
        mock_client.get_collection.return_value = mock_collection

        rag = self._rag_with_mock_client(mock_client)
        rag.search("col1", "q", where={"source": "web"})

        call_kwargs = mock_collection.query.call_args.kwargs
        assert call_kwargs["where"] == {"source": "web"}


@pytest.mark.unit
class TestRAGManagerDeleteCollection:
    """Tests for RAGManager.delete_collection()."""

    def _rag_with_mock_client(self, mock_client):
        from app.core.rag_manager import RAGManager
        rag = RAGManager()
        rag._client = mock_client
        return rag

    def test_calls_delete_on_client(self):
        """Calls client.delete_collection() with the collection name."""
        mock_client = MagicMock()
        rag = self._rag_with_mock_client(mock_client)
        rag.delete_collection("my_col")
        mock_client.delete_collection.assert_called_once_with("my_col")

    def test_suppresses_exception_on_delete_failure(self):
        """Does not propagate exceptions if delete_collection fails."""
        mock_client = MagicMock()
        mock_client.delete_collection.side_effect = Exception("Not found")
        rag = self._rag_with_mock_client(mock_client)
        rag.delete_collection("nonexistent")  # Should not raise


@pytest.mark.unit
class TestGetRagManager:
    """Tests for get_rag_manager() singleton factory."""

    def test_returns_rag_manager_instance(self):
        """Returns a RAGManager (or subclass) instance."""
        import app.core.rag_manager as mod
        saved = mod._rag_manager
        try:
            mod._rag_manager = None
            with patch("app.core.config.settings") as mock_settings:
                mock_settings.chroma_persist_directory = ""
                result = mod.get_rag_manager()
            from app.core.rag_manager import RAGManager
            assert isinstance(result, RAGManager)
        finally:
            mod._rag_manager = saved

    def test_returns_same_instance_on_second_call(self):
        """The singleton is reused across calls."""
        import app.core.rag_manager as mod
        saved = mod._rag_manager
        try:
            mod._rag_manager = None
            with patch("app.core.config.settings") as mock_settings:
                mock_settings.chroma_persist_directory = ""
                r1 = mod.get_rag_manager()
                r2 = mod.get_rag_manager()
            assert r1 is r2
        finally:
            mod._rag_manager = saved
