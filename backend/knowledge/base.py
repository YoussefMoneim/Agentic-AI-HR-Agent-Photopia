"""
KnowledgeBase — abstract interface for the vector knowledge layer.

The HR agent and ALL future agents NEVER touch pgvector, Azure AI Search,
or any vector store directly. They always go through this interface.

This is the "design/execute" separation Raef described:
- Design layer (feeder agent): ingests documents, builds knowledge
- Execute layer (HR agent tools): retrieves knowledge at runtime

Current implementation: PgvectorKnowledgeBase (Phase 1)
Future implementation:  AzureAISearchKnowledgeBase (Phase 7, when
                        Fotopia subscription available)

Swapping backing stores = implement this interface + change one line
in factory.py. Zero changes to HR agent or any tools.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class KnowledgeChunk:
    """A single retrievable unit of knowledge from the vector store."""
    chunk_id: str
    document_id: str
    document_name: str
    document_type: str
    access_level: str          # 'all' | 'hr_manager' | 'admin'
    chunk_text: str
    chunk_index: int
    similarity_score: float    # 0.0–1.0, higher = more semantically relevant
    metadata: dict = field(default_factory=dict)
    source_url: Optional[str] = None


@dataclass
class IngestResult:
    """Result of a document ingestion operation."""
    document_id: str
    document_name: str
    chunks_created: int
    chunks_replaced: int       # chunks deactivated from previous version
    success: bool
    error: Optional[str] = None


class KnowledgeBase:
    """
    Abstract interface — implement this to swap vector backing stores.

    Access control model:
        'employee'   → can retrieve access_level='all' only
        'hr_staff'   → can retrieve 'all' + 'hr_manager'
        'hr_manager' → can retrieve 'all' + 'hr_manager'
        'admin'      → can retrieve all levels
    """

    def search(
        self,
        query: str,
        tenant_id: str,
        user_role: str,
        top_k: int = 5,
        document_type: Optional[str] = None,
    ) -> list[KnowledgeChunk]:
        """
        Semantic search — find chunks most relevant to query.

        Enforces access_level filtering based on user_role.
        Results ordered by semantic similarity descending.
        """
        raise NotImplementedError

    def ingest(
        self,
        content: str,
        document_name: str,
        document_type: str,
        tenant_id: str,
        access_level: str,
        ingested_by: str,
        metadata: Optional[dict] = None,
        source_url: Optional[str] = None,
    ) -> IngestResult:
        """
        Ingest a document — chunk, embed, store, deactivate old version.

        Idempotent: re-ingesting the same document_name deactivates
        the previous version and creates a fresh set of chunks.
        """
        raise NotImplementedError

    def delete_document(
        self,
        document_name: str,
        tenant_id: str,
    ) -> int:
        """Deactivate all chunks for a document. Returns count deactivated."""
        raise NotImplementedError

    def list_documents(
        self,
        tenant_id: str,
    ) -> list[dict]:
        """
        List all active ingested documents for a tenant.
        Returns [{document_id, document_name, document_type,
                  access_level, chunk_count, ingested_at}]
        """
        raise NotImplementedError
