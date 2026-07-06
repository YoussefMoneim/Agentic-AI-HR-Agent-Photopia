"""
PgvectorKnowledgeBase — Phase 1 implementation of KnowledgeBase interface.

Backed by the existing private_document_chunks table.
Does NOT create a new table — extends what already exists.

Key design decisions:
- Uses private_document_chunks (existing, tested, RLS-enforced, ACL-gated)
- Hybrid search: vector similarity + full-text fallback
  If embeddings are not populated yet, falls back to existing full-text search
  so the tool never breaks during the transition period.
- classified_at: set to NOW() on ingestion (matches existing convention)
  NULL = quarantine = never returned. This is enforced in SQL, not Python.
- ACL: uses allowed_roles TEXT[] (existing column) not a new access_level enum
  Maps user roles to allowed_roles lists matching existing ACL_MAP convention.

Embedding model: voyage-multilingual-2
- "voyage-3-multilingual" does not exist in Voyage's current API (confirmed
  live: InvalidRequestError lists supported models) — voyage-multilingual-2
  is the real multilingual model name and also returns 1024-dim vectors,
  confirmed live against the real API.
- Handles Arabic + English (critical for WIN Holding)
- 1024 dimensions (matches migrated column)
"""
from __future__ import annotations
import logging
from typing import Optional

import voyageai
import psycopg2
import psycopg2.extras

from knowledge.base import KnowledgeBase, KnowledgeChunk, IngestResult
from knowledge.chunker import chunk_document

_log = logging.getLogger(__name__)

EMBEDDING_MODEL = "voyage-multilingual-2"
EMBEDDING_DIM = 1024
EMBED_BATCH_SIZE = 64

# Maps ToolContext.role → allowed_roles values accepted in ACL check
# Matches convention in existing ingest_policies.py ACL_MAP
_ROLE_TO_ALLOWED: dict[str, list[str]] = {
    "employee":   ["employee", "hr_staff", "hr_manager", "admin"],
    "hr_staff":   ["hr_staff", "hr_manager", "admin"],
    "hr_manager": ["hr_manager", "admin"],
    "admin":      ["admin"],
}

# Maps KnowledgeBase access_level → sensitivity + allowed_roles for storage
_ACCESS_TO_ACL: dict[str, dict] = {
    "all":        {"sensitivity": "public_tenant",
                   "allowed_roles": ["employee", "hr_staff", "hr_manager", "admin"]},
    "hr_manager": {"sensitivity": "restricted",
                   "allowed_roles": ["hr_manager", "admin"]},
    "admin":      {"sensitivity": "confidential",
                   "allowed_roles": ["admin"]},
}


class PgvectorKnowledgeBase(KnowledgeBase):

    def __init__(self, database_url: str, voyage_api_key: str):
        self._db_url = database_url
        self._voyage = voyageai.Client(api_key=voyage_api_key)

    def _conn(self):
        conn = psycopg2.connect(self._db_url)
        psycopg2.extras.register_uuid(conn)
        return conn

    def _set_tenant(self, cur, tenant_id: str) -> None:
        # Superusers bypass RLS even with FORCE — SET ROLE fotopia_app first,
        # matching the pattern in data/postgresql.py::_set_tenant.
        cur.execute("SET ROLE fotopia_app")
        cur.execute("SET app.current_tenant_id = %s", (tenant_id,))

    def _embed_documents(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        results = []
        for i in range(0, len(texts), EMBED_BATCH_SIZE):
            batch = texts[i: i + EMBED_BATCH_SIZE]
            resp = self._voyage.embed(
                batch, model=EMBEDDING_MODEL, input_type="document"
            )
            results.extend(resp.embeddings)
        return results

    def _embed_query(self, query: str) -> list[float]:
        resp = self._voyage.embed(
            [query], model=EMBEDDING_MODEL, input_type="query"
        )
        return resp.embeddings[0]

    def search(
        self,
        query: str,
        tenant_id: str,
        user_role: str,
        top_k: int = 5,
        document_type: Optional[str] = None,
    ) -> list[KnowledgeChunk]:
        """
        Hybrid search: vector similarity if embeddings present,
        full-text fallback if not. Never breaks during transition.
        ACL enforced in SQL before any result reaches Python.
        """
        # Determine which allowed_roles values this caller can see
        # The SQL check is: allowed_roles && caller_roles (overlap)
        # We pass the caller's role as a single-element array
        caller_roles = [user_role]

        conn = self._conn()
        try:
            with conn.cursor(
                cursor_factory=psycopg2.extras.RealDictCursor
            ) as cur:
                self._set_tenant(cur, tenant_id)

                # Check if any embeddings exist for this tenant
                cur.execute(
                    """
                    SELECT COUNT(*) as n
                    FROM private_document_chunks
                    WHERE tenant_id = %s AND embedding IS NOT NULL
                    """,
                    (tenant_id,),
                )
                has_embeddings = cur.fetchone()["n"] > 0

                query_embedding = None
                if has_embeddings:
                    try:
                        query_embedding = self._embed_query(query)
                    except Exception:
                        # Voyage call failed (rate limit, timeout, outage) — degrade
                        # to full-text rather than breaking the tool. This is the
                        # same "never breaks" promise as the no-embeddings-yet case,
                        # extended to cover a live-call failure too.
                        _log.warning(
                            "search: embedding call failed for tenant %s, "
                            "falling back to full-text",
                            tenant_id, exc_info=True,
                        )

                if query_embedding is not None:
                    # Vector similarity search
                    cur.execute(
                        """
                        SELECT
                            id::text            AS chunk_id,
                            document_id,
                            document_id         AS document_name,
                            'policy'            AS document_type,
                            sensitivity         AS access_level,
                            content             AS chunk_text,
                            chunk_index,
                            source_file         AS source_url,
                            1 - (embedding <=> %(qv)s::vector) AS similarity_score
                        FROM private_document_chunks
                        WHERE tenant_id = %(tid)s
                          AND classified_at IS NOT NULL
                          AND allowed_roles && %(roles)s::text[]
                        ORDER BY embedding <=> %(qv)s::vector
                        LIMIT %(k)s
                        """,
                        {
                            "qv":    query_embedding,
                            "tid":   tenant_id,
                            "roles": caller_roles,
                            "k":     top_k,
                        },
                    )
                else:
                    # Full-text fallback (existing behavior, always works)
                    _log.debug(
                        "search: no embeddings yet for tenant %s, "
                        "using full-text fallback",
                        tenant_id,
                    )
                    cur.execute(
                        """
                        WITH q AS (
                            SELECT string_agg(lexeme, ' | ') AS or_query
                            FROM unnest(to_tsvector('english', %(query)s))
                        )
                        SELECT
                            id::text  AS chunk_id,
                            document_id,
                            document_id  AS document_name,
                            'policy'     AS document_type,
                            sensitivity  AS access_level,
                            content      AS chunk_text,
                            chunk_index,
                            source_file  AS source_url,
                            ts_rank(content_tsv,
                                to_tsquery('english', q.or_query)
                            )::float     AS similarity_score
                        FROM private_document_chunks, q
                        WHERE q.or_query IS NOT NULL
                          AND tenant_id = %(tid)s
                          AND classified_at IS NOT NULL
                          AND allowed_roles && %(roles)s::text[]
                          AND content_tsv @@ to_tsquery('english', q.or_query)
                        ORDER BY similarity_score DESC
                        LIMIT %(k)s
                        """,
                        {
                            "query": query,
                            "tid":   tenant_id,
                            "roles": caller_roles,
                            "k":     top_k,
                        },
                    )

                rows = cur.fetchall()
                return [
                    KnowledgeChunk(
                        chunk_id=row["chunk_id"],
                        document_id=row["document_id"],
                        document_name=row["document_name"],
                        document_type=row["document_type"],
                        access_level=row["access_level"],
                        chunk_text=row["chunk_text"],
                        chunk_index=row["chunk_index"],
                        similarity_score=float(row["similarity_score"]),
                        source_url=row["source_url"],
                    )
                    for row in rows
                ]
        finally:
            conn.close()

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
        acl = _ACCESS_TO_ACL.get(access_level, _ACCESS_TO_ACL["all"])
        chunks = chunk_document(content, document_name)

        if not chunks:
            return IngestResult(
                document_id="",
                document_name=document_name,
                chunks_created=0,
                chunks_replaced=0,
                success=False,
                error=(
                    "No extractable text. If this is a scanned PDF, "
                    "run OCR first."
                ),
            )

        _log.info(
            "knowledge_base: embedding %d chunks for '%s'...",
            len(chunks), document_name
        )
        try:
            embeddings = self._embed_documents(chunks)
        except Exception as e:
            _log.exception(
                "knowledge_base: Voyage AI embedding failed for '%s'", document_name
            )
            return IngestResult(
                document_id="",
                document_name=document_name,
                chunks_created=0,
                chunks_replaced=0,
                success=False,
                error=f"Embedding generation failed: {e}",
            )

        conn = self._conn()
        try:
            with conn.cursor() as cur:
                self._set_tenant(cur, tenant_id)

                # Deactivate (delete) previous version
                cur.execute(
                    """
                    DELETE FROM private_document_chunks
                    WHERE tenant_id = %s AND document_id = %s
                    """,
                    (tenant_id, document_name),
                )
                replaced = cur.rowcount

                source = source_url or f"knowledge_base:{document_name}"

                for i, (text, embedding) in enumerate(
                    zip(chunks, embeddings)
                ):
                    cur.execute(
                        """
                        INSERT INTO private_document_chunks (
                            tenant_id, document_id, chunk_index, content,
                            embedding, sensitivity, allowed_roles,
                            source_file, classified_at
                        ) VALUES (
                            %s, %s, %s, %s,
                            %s::vector, %s, %s,
                            %s, NOW()
                        )
                        """,
                        (
                            tenant_id, document_name, i, text,
                            embedding, acl["sensitivity"], acl["allowed_roles"],
                            source,
                        ),
                    )

                conn.commit()

            _log.info(
                "knowledge_base: ingested '%s' → %d chunks "
                "(%d old deleted) for tenant %s",
                document_name, len(chunks), replaced, tenant_id
            )
            return IngestResult(
                document_id=document_name,
                document_name=document_name,
                chunks_created=len(chunks),
                chunks_replaced=replaced,
                success=True,
            )

        except Exception as e:
            conn.rollback()
            _log.exception(
                "knowledge_base: DB insert failed for '%s'", document_name
            )
            return IngestResult(
                document_id="",
                document_name=document_name,
                chunks_created=0,
                chunks_replaced=0,
                success=False,
                error=f"Database insert failed: {e}",
            )
        finally:
            conn.close()

    def delete_document(self, document_name: str, tenant_id: str) -> int:
        conn = self._conn()
        try:
            with conn.cursor() as cur:
                self._set_tenant(cur, tenant_id)
                cur.execute(
                    """
                    DELETE FROM private_document_chunks
                    WHERE tenant_id = %s AND document_id = %s
                    """,
                    (tenant_id, document_name),
                )
                count = cur.rowcount
                conn.commit()
                return count
        finally:
            conn.close()

    def list_documents(self, tenant_id: str) -> list[dict]:
        conn = self._conn()
        try:
            with conn.cursor(
                cursor_factory=psycopg2.extras.RealDictCursor
            ) as cur:
                self._set_tenant(cur, tenant_id)
                cur.execute(
                    """
                    SELECT
                        document_id,
                        sensitivity     AS access_level,
                        COUNT(*)        AS chunk_count,
                        MAX(created_at) AS ingested_at,
                        MAX(source_file) AS source_url
                    FROM private_document_chunks
                    WHERE tenant_id = %s
                      AND classified_at IS NOT NULL
                    GROUP BY document_id, sensitivity
                    ORDER BY MAX(created_at) DESC
                    """,
                    (tenant_id,),
                )
                return [dict(row) for row in cur.fetchall()]
        finally:
            conn.close()
