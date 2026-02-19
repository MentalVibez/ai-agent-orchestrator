"""RAG (Retrieval-Augmented Generation) API routes."""

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from app.core.auth import verify_api_key

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/rag", tags=["rag"])


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------


class IndexRequest(BaseModel):
    collection: str = Field(..., description="Collection name")
    document_id: str = Field(..., description="Unique document identifier")
    text: str = Field(..., description="Document text to embed and index")
    metadata: Optional[Dict[str, Any]] = Field(None, description="Optional metadata")


class SearchRequest(BaseModel):
    collection: str = Field(..., description="Collection name to search")
    query: str = Field(..., description="Search query string")
    n_results: int = Field(5, ge=1, le=100, description="Number of results to return")
    where: Optional[Dict[str, Any]] = Field(None, description="Optional metadata filter")


class SearchResult(BaseModel):
    id: str
    document: str
    metadata: Dict[str, Any]
    distance: Optional[float]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_rag():
    """Get RAGManager, raising 503 if chromadb is not installed."""
    try:
        from app.core.rag_manager import get_rag_manager

        return get_rag_manager()
    except ImportError as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"RAG unavailable: {e}",
        )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post("/index", status_code=status.HTTP_204_NO_CONTENT)
async def index_document(
    body: IndexRequest,
    api_key: str = Depends(verify_api_key),
):
    """
    Index (upsert) a document into a ChromaDB collection.
    Requires X-API-Key authentication.
    """
    rag = _get_rag()
    try:
        rag.index_document(
            collection_name=body.collection,
            document_id=body.document_id,
            text=body.text,
            metadata=body.metadata,
        )
    except Exception as e:
        logger.error("RAG index_document failed: %s", e)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


@router.post("/search", response_model=List[SearchResult])
async def search_documents(
    body: SearchRequest,
    api_key: str = Depends(verify_api_key),
):
    """
    Semantic search over a ChromaDB collection.
    Returns ranked results with distance scores.
    Requires X-API-Key authentication.
    """
    rag = _get_rag()
    try:
        results = rag.search(
            collection_name=body.collection,
            query=body.query,
            n_results=body.n_results,
            where=body.where,
        )
        return results
    except Exception as e:
        logger.error("RAG search failed: %s", e)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


@router.delete("/collection/{collection_name}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_collection(
    collection_name: str,
    api_key: str = Depends(verify_api_key),
):
    """
    Delete a ChromaDB collection and all its documents.
    Requires X-API-Key authentication.
    """
    rag = _get_rag()
    try:
        rag.delete_collection(collection_name)
    except Exception as e:
        logger.error("RAG delete_collection failed: %s", e)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


@router.get("/collections", response_model=List[str])
async def list_collections(
    api_key: str = Depends(verify_api_key),
):
    """
    List all existing ChromaDB collections.
    Requires X-API-Key authentication.
    """
    rag = _get_rag()
    try:
        return rag.list_collections()
    except Exception as e:
        logger.error("RAG list_collections failed: %s", e)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))
