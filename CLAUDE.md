# Fotopia HR Agent — Project Architecture & Rules

This file is read by Claude Code at the start of every session. It is the single source of truth for what this project is, what's built, what the rules are, and what comes next. Keep it updated as the project evolves — if a decision changes, update this file in the same session.

---

## 1. What this is

An enterprise SaaS AI agent platform that automates HR tasks for Fotopia Technologies' clients (banks, government bodies, healthcare orgs) across Egypt/MENA. Claude (Anthropic) is the LLM. The first pilot client is Fotopia itself — Nourhan Hosny (HR Project Lead) is the first real user. The product vision is a "shared service operator" marketplace — a Copilot-style sidebar of department agents (HR first, then Finance/Admin/Legal), where a subscribed agent already has the access it needs and the user just types what they need done.

---

## 2. Current status

**Phase 0 — Done.** Repo structure, Docker (Postgres + FastAPI), LLM abstraction (Claude + Grok), data abstraction (`PostgreSQLDataSource`), `ToolRegistry` gateway, `ToolContext`, `audit_log` table.

**Phase 1 — Done.** 10 employee/document tools registered and tested:
- `get_employee_data`, `search_employees`, `list_employees`, `get_leave_balance` (read)
- `get_employee_summary` (read, computes `years_of_service`)
- `get_employee_documents` / `get_employee_document_history` (read, queries audit_log)
- `generate_salary_certificate`, `generate_twimc_letter`, `generate_experience_certificate` (document generation — fpdf, ref codes SC-/TW-/EC-)
- `calculate_end_of_service` (deterministic Egyptian Labor Law gratuity calc, returns `calculation_breakdown`)

**Phase 1.5 — Done.** RLS `ENABLE` + `FORCE` on every tenant table, with a CI guardrail test (`backend/tests/test_security.py::TestRLSEnforced`, plus a cross-tenant zero-rows test). `MockDataSource` renamed to `PostgreSQLDataSource` (`backend/data/postgresql.py`, wired via `backend/data/factory.py`).

**Phase 2 — Partially done:**
- ✓ Real JWT authentication (`backend/core/auth.py::decode_context`) replaces the `build_context()` stub. A `DEBUG_ALLOW_DEMO_ROLE` fallback still exists for local development but a startup assertion in `config.py` refuses it outside `APP_ENV in (local, dev)`.
- ✓ **Full leave-management feature**, well beyond the original Phase 1 scope: submit → eligibility → approve/reject → cancel lifecycle, cancellation-of-already-approved-leave, a team leave calendar, the full WIN Holding Leave Policy engine (`HR/BTE 001/7-2025` — 17 leave types, notice periods, service minimums, career usage caps, carry-over expiry, casual sub-quota, 25% department concurrent cap), a deterministic constraint engine (hard/soft/advisory rules, `backend/workflow/constraints.py`), a document-sensitivity appropriateness layer (`backend/workflow/appropriateness.py`), a bidirectional email approval agent (SMTP send + IMAP reply parsing, correlation tokens, rate limiting), and one-way Odoo sync for approved/cancelled leave. Covered by ~283 passing tests.
- ✓ **Feeder-agent knowledge layer (Phase 1 of the Zumra "design/execute" split — feeder agent ingests, HR agent tools retrieve, see Layer 7 below)**: `KnowledgeBase` abstract interface (`backend/knowledge/base.py`) so tools never touch pgvector directly; `PgvectorKnowledgeBase` (`backend/knowledge/pgvector_kb.py`) backed by the existing `private_document_chunks` table — no new table, RLS/ACL unchanged from Phase 1.5 (`allowed_roles`, `sensitivity`, `classified_at` quarantine). Voyage AI (`voyage-multilingual-2`, 1024-dim) embeddings for semantic search, with automatic full-text fallback if embeddings aren't populated yet or the Voyage call fails — ACL is pre-filtered in the SQL `WHERE` clause in both cases (Rule 14 compliant). `search_policy` tool now goes through `KnowledgeBase`, not the data layer directly. A SharePoint connector (`backend/connectors/sharepoint.py`, Microsoft Graph delta-sync, `sharepoint_sync_state` table) auto-ingests policy documents from a watched folder.
- 🔲 Still open: Redis session history (still an in-memory `_sessions` dict), onboarding document-gen tools, ZDR agreement with Anthropic, document ingest API endpoints (`POST /api/knowledge/ingest` — ingestion today is script/connector-driven only, no HR-manager-facing upload endpoint yet), Tier 1 `public_knowledge_chunks` table (schema exists, no ingestion path populates it), `VOYAGE_API_KEY` is required at `build_registry()` time — not documented anywhere before this note, and its absence fails the entire registry (and therefore every test that touches it), not just knowledge tools.

**Phase 3+ — Not started.** Audit log hash-chaining/WORM, field-level encryption, onboarding state-machine writes. RAG metadata-audit tooling and Tier 1 public-knowledge ingestion remain open under the knowledge layer above. See Section 7.

---

## 3. The complete architecture (current + future layers)

Layers 1-6 and 9 exist today (in some form). Layers 7-8 and the parallel/future layers are NOT built yet — they are designed so that building them later requires ADDING, not rewriting.

```
1. PRESENTATION
   React + Vite (not Next.js) — chat, approval inbox, team leave calendar,
   document library, and audit log view are already built
   (frontend/src/components/: ChatInterface, ApprovalInbox, LeaveCalendar,
   DocumentLibrary, AuditLog).

2. API / IDENTITY LAYER                                    [EXISTS — real JWT]
   FastAPI. _build_context() validates a real JWT (core/auth.py::decode_context)
   today. A DEBUG_ALLOW_DEMO_ROLE fallback exists for local dev only — a
   startup assertion in config.py refuses it outside APP_ENV in (local, dev).
   ToolContext = {tenant_id, user_id, role, employee_code}

3. ORCHESTRATOR LAYER                                       [EXISTS]
   Raw Anthropic SDK tool_use loop, MAX_ITERS=10.
   Conversation history stored server-side in _sessions dict (in-memory;
   Phase 2 moves this to Redis so history survives server restarts).
   FUTURE: LangGraph state machine runs ALONGSIDE this (not instead of) for
   onboarding-style multi-day workflows that pause for human approval.
   Both call the SAME ToolRegistry.execute() — one security model either way.

4. TOOL GATEWAY                                             [EXISTS — the security boundary]
   ToolRegistry:
     - schemas_for(ctx): filters tool list by role BEFORE the LLM call
       ("policy before prompt" — Claude never sees tools it can't use)
     - execute(name, args, ctx): re-checks role, runs the tool, audits
       EVERY call (success, failure, or denial)

5. TOOLS                                                    [EXISTS, growing]
   READ          — employee data, leave balance, summaries, document history
   DOCUMENT GEN  — salary cert, TWIMC, experience cert, (future: contracts,
                   payslips, offer letters — all fpdf, hardcoded bilingual
                   templates, DB-driven content, LLM never invents content
                   or does math)
   CALCULATION   — end-of-service gratuity (pure Python, never the LLM)
   LEAVE (HITL)  — full lifecycle built and tested: submit/eligibility/
                   approve/reject/cancel, cancellation-of-approved-leave,
                   team calendar, WIN Holding policy engine, deterministic
                   constraint engine (hard/soft/advisory), email + Odoo
                   sync — see backend/tools/leave.py, backend/workflow/.
   WRITE (HITL)  — FUTURE: create_employee_record, enroll_social_insurance
                   — MUST require human approval, see Section 6
   COMMUNICATION — FUTURE: notify_finance, send_welcome_email — draft-only
                   by default, see Section 6
   ORCHESTRATION — FUTURE: onboarding checklist/status tools

   Row-level access (core/access.py::can_access — HR sees all, employee sees
   only self) enforced inside tools via ToolContext, AND mirrored by database
   RLS with FORCE (Phase 1.5 — done, defense in depth — both layers check).

6. DATA LAYER — PostgreSQL                                  [EXISTS — RLS FORCED]
   tenant_id on every table, every query. DataSource abstraction:
   PostgreSQLDataSource (backend/data/postgresql.py) is the real
   implementation, wired via backend/data/factory.py; odoo_sync.py
   syncs approved/cancelled leave one-way to Odoo.
   RLS ENABLE + FORCE on every tenant table (migration 001_add_rls.sql),
   with a CI guardrail test (test_security.py::TestRLSEnforced).
   FUTURE: per-tenant database option for premium clients,
   field-level encryption for national_id/salary (blind index pattern).

7. KNOWLEDGE / RAG LAYER                                    [PARTIALLY BUILT — Phase 1 of feeder agent]
   pgvector, co-located with the relational DB (inherits RLS). Accessed ONLY
   through the KnowledgeBase interface (backend/knowledge/base.py) — this is
   the Zumra "design/execute" split: the feeder agent (ingestion scripts +
   SharePoint connector) does design-time ingestion, HR agent tools do
   execute-time retrieval, both through the same interface so a future swap
   to Azure AI Search (Phase 7) is one factory-line change.
   Tier 2/3 (private_document_chunks, tenant-scoped): every chunk carries
   tenant_id + allowed_roles + sensitivity + classified_at (NULL = quarantine,
   fail-closed). Retrieval filters on this metadata in the SQL WHERE clause
   BEFORE the vector similarity ORDER BY — never after (the EchoLeak/Copilot
   lesson, see Section 6, Rule 14). NOT YET: owner_employee_id-scoped chunks
   for personally-owned (non-policy) documents — today's chunks are all
   role-gated, not per-employee-owned.
   document_id is canonicalized (knowledge/chunker.py::canonical_document_id)
   across every ingestion path so the same document re-ingested via a
   different path dedupes instead of accumulating duplicate chunks.
   Tier 1 (public/legal reference data) — public_knowledge_chunks table
   exists (no tenant_id, no RLS) but has no ingestion path yet; unused.
   Client-uploaded documents: human-classified, fail-CLOSED (most
   restrictive label) if unclassified — labeling convention still applies,
   not yet wired to a human-classification UI.

8. LLM LAYER                                                [EXISTS — Claude/Grok swappable]
   claude.py is the ONLY file importing the Anthropic SDK. Stateless per
   request — context built ONLY from data already authorized at layers 5-7.
   FUTURE: signed Zero Data Retention (ZDR) agreement before any real client
   data goes through Claude (see Section 9, open item #1 — may also require
   self-hosted Llama/Qwen depending on the legal answer; the abstraction
   already supports this via LLM_PROVIDER with zero tool/registry changes).

9. AUDIT LAYER                                              [EXISTS, needs hardening]
   audit_log — every tool call, every decision (allowed/denied/error),
   written by the registry, never bypassed.
   FUTURE (Phase 3): hash-chain each row to the previous (tamper-evidence),
   mirror to append-only/WORM storage, redact/tokenize PII before write.


PARALLEL — STATEFUL WORKFLOW LAYER                          [PARTIALLY BUILT]
   workflow_instances, pending_actions, workflow_events already exist
   (tenant_id-scoped) and are in production use today for the leave-approval
   HITL flow (backend/workflow/). NOT YET BUILT: onboarding_cases,
   onboarding_tasks, onboarding_documents — the onboarding-specific state
   machine (Phase 2/3) can reuse the existing pending_actions primitive
   rather than building a new one from scratch. The LangGraph state machine
   (layer 3) for multi-day onboarding workflows is still not built.


FUTURE — PROACTIVE "JARVIS" LAYER                           [NOT BUILT — Phase 4]
   Stage 1: get_daily_briefing — READ-ONLY aggregation (pending approvals,
            upcoming deadlines, recent activity). Ships first, low risk.
   Stage 2: goals / goal_tasks tables — planning/checklist data, no
            autonomous action.
   Stage 3: "approve -> executes via existing ToolRegistry" — the
            autonomous-feeling experience, built on Stage 1+2 data.
   NEVER: live self-modifying prompts/behavior (see Rule 11).
```

---

## 4. Locked decisions

| Decision | Choice | Why |
|---|---|---|
| LLM | Claude (claude-sonnet-4-5) via Anthropic SDK, behind `LLMProvider` | Swappable to self-hosted for regulated/on-prem clients via one env var |
| Orchestration | Raw Anthropic SDK loop now; LangGraph added alongside for stateful onboarding | Both call the same `ToolRegistry.execute()` — one security model |
| Session history | In-memory `_sessions` dict now; Redis in Phase 2 | Survives tool calls within a session; Redis makes it survive server restarts |
| Data | PostgreSQL, `DataSource` abstraction (mock now, Odoo later) | Same interface either way |
| Multi-tenancy | `tenant_id` on every table/query, hybrid shared-schema+RLS with database-per-tenant option for premium clients | Validated against real multi-tenant SaaS patterns |
| Security pattern | "Policy before prompt" — `ToolRegistry` filters tools by role BEFORE the LLM call, re-checks at execution, audits everything | Access control lives in tools/DB, never in the prompt |
| Salary/math | Never done by the LLM — deterministic Python only | A wrong number on a legal document is a lawsuit |
| Documents | Hardcoded fpdf templates, DB-driven slot-filling | LLM never invents content; consistent output every time |
| RAG | Metadata pre-filter (tenant_id + allowed_roles) BEFORE semantic search — implemented in `PgvectorKnowledgeBase.search()`'s SQL WHERE clause | The EchoLeak/Copilot lesson — filtering after search is too late |
| Prompt optimization | Offline only (DSPy/GEPA, frozen + human-reviewed artifact) — NEVER live self-modifying prompts | Live optimization is unauditable and a security risk (RBAC must never live near a prompt an optimizer can touch) |
| Proactive/"Jarvis" layer | Staged: shadow-mode briefing -> goal tracking -> assisted execution via existing registry | Never an autonomous agent with general computer/file access |

---

## 5. The role/access model

**Today — 4 roles:** `employee`, `hr_staff`, `hr_manager`, `admin`. Defined per-tool via `allowed_roles`. Row-level: `_can_access_employee()` — HR roles see everyone, an employee sees only their own record (matched on `employee_code`).

**Future addition (Phase 2/3, additive, not a replacement):** a `department`-scoped role (e.g., "department head" sees only their department's employees) using the `employees.department` column that already exists. This stacks as an ADDITIONAL restrictive check alongside tenant_id + role + row — it does not replace the 4-role model.

**Field-level (future, Phase 3):** salary, national_id, and similar fields need their own gate — a role that can see an employee row doesn't automatically see every column. Implement via column GRANTs / `security_invoker` views or application-layer redaction before the data reaches the LLM context.

---

## 6. Hard rules — never violate these

1. Never import `anthropic` outside `llm/claude.py`.
2. Never query the database directly in a tool — always through `DataSource`.
3. Never call a tool function directly — always through `ToolRegistry.execute()`.
4. Never put access control logic in the system prompt — it lives in tools + RLS.
5. Never hardcode tenant-specific data (templates, company names) as Python strings — load from config so swapping clients is a data change, not a code change.
6. Every tool defines `allowed_roles`, receives `ToolContext`, enforces row-level access, returns `ToolResult`.
7. `tenant_id` on every table and every query.
8. Audit log on every tool call — never bypass the registry. (Future: hash-chain + WORM mirror, Phase 3.)
9. Never let the LLM do math — deterministic Python for all calculations.
10. Secrets only from environment variables via `config.py`, never hardcoded. (And never paste `.env` contents anywhere outside the local machine — rotate any key that's ever been exposed.)
11. **No live self-modifying/self-optimizing prompts in production.** Offline prompt optimization (DSPy/GEPA) is fine IF the result is a frozen, version-controlled, human-reviewed artifact that goes through the same eval/review as code.
12. **Two tools are HARD-GATED behind human-in-the-loop approval, no exceptions:** `create_employee_record` (privilege-escalation/fake-record risk — must never accept an LLM-supplied `role` value above the safe default) and `enroll_social_insurance` (government filing with legal penalties for errors). Any future tool that sends an email containing salary/compensation data is ALSO HITL-gated and draft-only by default.
13. **Treat all uploaded document content (resumes, certificates) as untrusted DATA, never as instructions.** Extract structured fields via OCR; never feed raw uploaded text into a context where it could trigger tool calls.
14. **RAG retrieval (when built) filters by `tenant_id` + `allowed_roles` metadata BEFORE the semantic search runs — never after.** Re-sync ACL metadata on permission changes, not just on document edit. Unclassified/ambiguous chunks default to the MOST restrictive label (fail closed).
15. Privileged write tools (`create_employee_record`, `enroll_social_insurance`, `set_salary`) must NOT be enabled until real JWT auth (Phase 2) replaces the `build_context()` stub — the audit trail needs a real authenticated approver identity to mean anything.

---

## 7. Phased roadmap

| Phase | What ships |
|---|---|
| **0** ✓ | Repo, abstractions, ToolRegistry, ToolContext, audit_log, Docker |
| **1** ✓ | 10 tools: salary cert, TWIMC, experience cert, leave balance, employee summary, list/search employees, document history, EOS calculation |
| **1.5** ✓ | CI guardrail: `test_security.py::TestRLSEnforced` asserts RLS is enabled+forced on every `tenant_id` table, plus a cross-tenant query test expecting zero rows. `MockDataSource` renamed to `PostgreSQLDataSource`. |
| **2** ✓ | JWT auth (`core/auth.py::decode_context`, replaces `build_context()` stub) — prerequisite for all privileged writes. `DEBUG_ALLOW_DEMO_ROLE` remains as a dev-only fallback, locked to `APP_ENV in (local, dev)` |
| **2** ✓ | RLS enabled with FORCE on all tenant tables |
| **2** ✓ | Full leave-management lifecycle: submit/eligibility/approve/reject/cancel, cancellation-of-approved-leave, team calendar, WIN Holding Leave Policy engine (17 types), constraint engine (hard/soft/advisory), appropriateness layer, bidirectional email approval agent, Odoo sync. ~283 passing tests |
| **2** ✓ | Feeder-agent knowledge layer Phase 1: `KnowledgeBase` abstraction, `PgvectorKnowledgeBase`, Voyage AI embeddings + full-text fallback, SharePoint connector. See Section 2. |
| **2** 🔲 next | Redis for session history (replaces in-memory _sessions dict) |
| **2** 🔲 | Onboarding Phase 1: document-gen tools only (offer letter, bilingual employment contract, NDA, checklist) — no writes yet |
| **2** 🔲 | Role/field RESTRICTIVE policies (Tier 3) — RLS today is tenant-scoped only, not yet role/field-scoped at the DB layer |
| **2** 🔲 | ZDR agreement with Anthropic — pursue in parallel with open item #1 below |
| **2** 🔲 | Knowledge layer follow-ups: document ingest API endpoint, Tier 1 `public_knowledge_chunks` ingestion path, `VOYAGE_API_KEY` documented as a hard registry-build dependency |
| **3** 🔲 | Onboarding Phase 2: `onboarding_cases` state machine + gated writes (Rule 12) — can reuse the existing `pending_actions` table already proven by the leave-approval flow |
| **3** 🔲 | RAG/knowledge layer remainder — owner_employee_id-scoped personal documents, human-classification UI for uploads, Tier 1/2/3 separation completed (Rule 14) |
| **3** 🔲 | Audit log hash-chaining + WORM mirror (Rule 8) |
| **3** 🔲 | Field-level encryption for national_id, salary (blind index pattern, Section 5) |
| **4** 🔲 | Database-per-tenant option for premium banking/gov clients |
| **4** 🔲 | Offline APO (DSPy/GEPA) once a labeled eval dataset exists (Rule 11) |
| **4** 🔲 | "Jarvis" proactive layer — shadow-mode briefing -> goal tracking -> assisted execution |

---

## 8. DigitizeMe integration note (future)

Fotopia's capture service uses a `tenant -> department -> batch class` hierarchy. "Batch class" = a per-document-type processing template (extraction rules, routing — NOT an access-control concept). If DigitizeMe becomes the document storage backend:

- Our `tenant_id` maps directly to DigitizeMe's tenant (already aligned — no change needed).
- Each of our document TYPES (salary_certificate, twimc_letter, experience_certificate, future contract/payslip types) should map 1:1 to a DigitizeMe "batch class" when filed — this is the same labeling pattern we already chose for RAG (Rule 14/Layer 7), just reused for a different product's storage layer.
- Department-level access (if added per Section 5) stays an internal Tier-3 concern — it does not need to map onto DigitizeMe's department concept, which is about document routing, not permissions.

---

## 9. Open items — business/legal, not engineering (raise with Dr. Ahmed/Raef)

1. **(Urgent, parallel-track)** Egypt PDPL cross-border transfer — does sending tenant data to Claude's cloud API require a PDPC license? Affects whether real client data can go through cloud Claude. Engineering continues on mock data regardless (no real exposure with synthetic Saif/Omar/Nourhan records) — but this blocks real-client go-live.
2. **DPO appointment** — PDPL requires a registered Data Protection Officer before processing sensitive data (salary + national ID are both "sensitive" under Egyptian law) at scale.
3. **HITL approval ownership** — for onboarding's gated actions (Rule 12), who is the designated human approver? Org-chart question the architecture assumes an answer to.
4. **Document-verification vendor** — if automated ID/certificate verification is wanted for onboarding, Valify (Egypt-specific) was the strongest option found — needs a procurement decision.
5. **Eval dataset for offline optimization (Phase 4)** — building a labeled set of "good vs bad" agent responses needs real HR-manager time; flag as a future ask.

---

## 10. Running the project

```bash
cp .env.example .env          # add your ANTHROPIC_API_KEY / GROK_API_KEY — never commit this file
docker compose up              # Postgres (auto-loads schema+seed) + backend
curl localhost:8000/health

# Talk to the agent
curl -X POST localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"message":"Generate a salary certificate for Saif Ahmed for bank account opening"}'

# Watch the audit log live
watch -n 2 'docker exec fotopia-hr-agent-db-1 psql -U fotopia -d fotopia_hr \
  -c "SELECT tool_name, actor_role, outcome, result_summary, latency_ms, created_at \
      FROM audit_log ORDER BY created_at DESC LIMIT 10;"'
```

---

## 11. Who is involved

- **Youssef (Joe) Abdelmoneim** — building this (Computer Engineering, AUS, AI/ML intern)
- **Dr. Ahmed El-Yazbi** — R&D AI Director, main technical stakeholder
- **Raef Eid** — Founder/chief software architect, product vision owner
- **Nourhan Hosny** — HR Project Lead, first real user
- **Fotopia Technologies** — Cairo, document management company under WIN Holding Group
- **DigitizeMe** — Fotopia's document management product, potential storage backend (Section 8)
