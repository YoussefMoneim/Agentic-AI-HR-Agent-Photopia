# ADR-002: One SearchPolicyTool with hybrid fallback (not two tools)
Date: 2026-07-09
Status: Accepted

## Decision
`SearchPolicyTool` is the single entry point for HR policy questions. A previous `DataSource.search_policy()` method has been removed entirely — it must never be called or reintroduced. `SearchPolicyTool` calls `KnowledgeBase.search()`, which performs vector similarity search when embeddings exist for a tenant and falls back to PostgreSQL full-text search when they don't, so retrieval never breaks during the transition period before every document has an embedding.

## Why
The knowledge base boundary requires that pgvector is never called directly and `KnowledgeBase` (`backend/knowledge/base.py`) is the only interface tools are allowed to use — this keeps the pgvector-to-Azure-AI-Search swap in `knowledge/factory.py` transparent to every caller. Consolidating on one tool also keeps every retrieval call auditable through the `ToolRegistry`, instead of splitting policy lookups across two code paths (a direct `DataSource` method and a proper tool) with different security and audit properties.

## Consequences
Any future retrieval need (contract search, onboarding document search, etc.) should extend `SearchPolicyTool`/`KnowledgeBase` rather than adding a second, parallel search path back through `DataSource`. Result ranking is not directly comparable between the two search modes (cosine similarity vs. `ts_rank`) until every chunk has an embedding populated — this is an accepted, known tradeoff of the fallback, not a bug to fix.
