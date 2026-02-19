"""
RAG (Retrieval-Augmented Generation) manager using ChromaDB.

ChromaDB is an optional dependency. If not installed, all operations raise ImportError.
Install with: pip install chromadb>=0.4
"""

import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


def _get_chromadb():
    """Lazy import of chromadb so the rest of the app works without it."""
    try:
        import chromadb

        return chromadb
    except ImportError as e:
        raise ImportError(
            "chromadb is required for RAG features. Install with: pip install chromadb>=0.4"
        ) from e


class RAGManager:
    """
    Manage document indexing and semantic search via ChromaDB.

    Usage:
        rag = RAGManager()
        rag.index_document("my_collection", "doc1", "Some document text", {"source": "web"})
        results = rag.search("my_collection", "query text", n_results=5)
    """

    def __init__(self, persist_directory: Optional[str] = None) -> None:
        """
        Initialize RAGManager.

        Args:
            persist_directory: Optional path to persist ChromaDB on disk.
                               If None, uses in-memory (ephemeral) storage.
        """
        self._persist_directory = persist_directory
        self._client = None

    def _get_client(self):
        """Lazily initialize ChromaDB client."""
        if self._client is None:
            chromadb = _get_chromadb()
            if self._persist_directory:
                self._client = chromadb.PersistentClient(path=self._persist_directory)
                logger.info("ChromaDB initialized (persist_dir=%s)", self._persist_directory)
            else:
                self._client = chromadb.Client()
                logger.info("ChromaDB initialized (in-memory)")
        return self._client

    def index_document(
        self,
        collection_name: str,
        document_id: str,
        text: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """
        Add or update a document in the specified collection.

        Args:
            collection_name: ChromaDB collection name
            document_id: Unique document identifier (used for upsert)
            text: Document text to embed and index
            metadata: Optional metadata dict (must have string values for ChromaDB)
        """
        client = self._get_client()
        collection = client.get_or_create_collection(collection_name)
        safe_meta: Dict[str, str] = {
            k: str(v) for k, v in (metadata or {}).items()
        }
        collection.upsert(
            ids=[document_id],
            documents=[text],
            metadatas=[safe_meta] if safe_meta else None,
        )
        logger.debug("Indexed document %s into collection %s", document_id, collection_name)

    def search(
        self,
        collection_name: str,
        query: str,
        n_results: int = 5,
        where: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        """
        Semantic search over a collection.

        Args:
            collection_name: ChromaDB collection name
            query: Query string
            n_results: Maximum number of results to return
            where: Optional ChromaDB metadata filter

        Returns:
            List of dicts with keys: id, document, metadata, distance
        """
        client = self._get_client()
        try:
            collection = client.get_collection(collection_name)
        except Exception:
            logger.warning("Collection %s does not exist; returning empty results", collection_name)
            return []

        kwargs: Dict[str, Any] = {
            "query_texts": [query],
            "n_results": min(n_results, collection.count() or 1),
        }
        if where:
            kwargs["where"] = where

        results = collection.query(**kwargs)
        output: List[Dict[str, Any]] = []
        ids = (results.get("ids") or [[]])[0]
        documents = (results.get("documents") or [[]])[0]
        metadatas = (results.get("metadatas") or [[]])[0]
        distances = (results.get("distances") or [[]])[0]

        for i, doc_id in enumerate(ids):
            output.append(
                {
                    "id": doc_id,
                    "document": documents[i] if i < len(documents) else "",
                    "metadata": metadatas[i] if i < len(metadatas) else {},
                    "distance": distances[i] if i < len(distances) else None,
                }
            )
        return output

    def delete_collection(self, collection_name: str) -> None:
        """
        Delete an entire collection.

        Args:
            collection_name: Collection to delete
        """
        client = self._get_client()
        try:
            client.delete_collection(collection_name)
            logger.info("Deleted collection %s", collection_name)
        except Exception as e:
            logger.warning("Could not delete collection %s: %s", collection_name, e)

    def list_collections(self) -> List[str]:
        """Return names of all existing collections."""
        client = self._get_client()
        return [c.name for c in client.list_collections()]


# Module-level singleton
_rag_manager: Optional[RAGManager] = None


def get_rag_manager(persist_directory: Optional[str] = None) -> RAGManager:
    """
    Get (or create) the global RAGManager instance.

    Args:
        persist_directory: Passed only on first call; ignored on subsequent calls.
    """
    global _rag_manager
    if _rag_manager is None:
        _rag_manager = RAGManager(persist_directory=persist_directory)
    return _rag_manager
