# ADR-001: pgvector over a dedicated vector database
Date: 2026-07-09
Status: Accepted

## Decision
The knowledge/RAG layer (Layer 7 of the architecture) uses pgvector, co-located in the same PostgreSQL instance as the rest of the tenant-scoped relational data, rather than a separate, dedicated vector database.

## Why
Because the vector store lives inside the same Postgres instance and inherits Row-Level Security, tenant isolation for policy-document chunks does not need a second, independently-built security model — every chunk still carries `tenant_id` + `allowed_roles` + `owner_employee_id`, and retrieval filters on that metadata before semantic search runs, never after (the explicit lesson drawn from the EchoLeak/Copilot RAG failures).

## Consequences
Because ACL enforcement for retrieval must happen as a metadata pre-filter at the SQL layer rather than as a bolt-on after search, the knowledge base's access model stays consistent with every other tenant table in the system (RLS + `tenant_id` everywhere) instead of introducing a second access-control mechanism to keep in sync. Tier 1 (public/legal reference data, shared across all tenants) is kept in a separate table with no `tenant_id` and no RLS, since it is explicitly not tenant-scoped data.
