"""
KnowledgeBase factory.

Phase 1: PgvectorKnowledgeBase backed by private_document_chunks.
Phase 7: Swap to AzureAISearchKnowledgeBase when Fotopia subscription available.
Change here only — HR agent and all tools unchanged.
"""
from __future__ import annotations
from functools import lru_cache
from knowledge.base import KnowledgeBase


@lru_cache(maxsize=1)
def get_knowledge_base() -> KnowledgeBase:
    import config
    from knowledge.pgvector_kb import PgvectorKnowledgeBase

    if not getattr(config, "VOYAGE_API_KEY", ""):
        raise RuntimeError(
            "VOYAGE_API_KEY not set. "
            "Get a free key at https://www.voyageai.com "
            "and add VOYAGE_API_KEY=your_key to .env"
        )

    return PgvectorKnowledgeBase(
        database_url=config.DATABASE_URL,
        voyage_api_key=config.VOYAGE_API_KEY,
    )
