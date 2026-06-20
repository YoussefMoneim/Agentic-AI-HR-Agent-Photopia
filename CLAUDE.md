# Fotopia HR Agent — Project Architecture & Rules

This file is read by Claude Code at the start of every session. It is the single source of truth for what this project is, what's built, what the rules are, and what comes next. Keep it updated as the project evolves — if a decision changes, update this file in the same session.

---

## 1. What this is

An enterprise SaaS AI agent platform that automates HR tasks for Fotopia Technologies' clients (banks, government bodies, healthcare orgs) across Egypt/MENA. Claude (Anthropic) is the LLM. The first pilot client is Fotopia itself — Nourhan Hosny (HR Project Lead) is the first real user. The product vision is a "shared service operator" marketplace — a Copilot-style sidebar of department agents (HR first, then Finance/Admin/Legal), where a subscribed agent already has the access it needs and the user just types what they need done.

---

## 2. Current status

**Phase 0 — Done.** Repo structure, Docker (Postgres + FastAPI), LLM abstraction (Claude + Grok), data abstraction (mock/Postgres), `ToolRegistry` gateway, `ToolContext`, `audit_log` table.

**Phase 1 — Done.** 10 tools registered and tested:
- `get_employee_data`, `search_employees`, `list_employees`, `get_leave_balance` (read)
- `get_employee_summary` (read, computes `years_of_service`)
- `get_employee_documents` / `get_employee_document_history` (read, queries audit_log)
- `generate_salary_certificate`, `generate_twimc_letter`, `generate_experience_certificate` (document generation — fpdf, ref codes SC-/TW-/EC-)
- `calculate_end_of_service` (deterministic Egyptian Labor Law gratuity calc, returns `calculation_breakdown`)

**Phase 1.5 — Next.** Hardening before more tools get added (see Section 7, Phase 1.5).

**Phase 2+ — Onboarding + security hardening.** See Section 7.

---

## 3. The complete architecture (current + future layers)

Layers 1-6 and 9 exist today (in some form). Layers 7-8 and the parallel/future layers are NOT built yet — they are designed so that building them later requires ADDING, not rewriting.

```
1. PRESENTATION
   React/Next.js — search, chat, document preview, (future: approval inbox)

2. API / IDENTITY LAYER                                    [EXISTS — stubbed]
   FastAPI. build_context() returns a stubbed HR-manager ToolContext today.
   Phase 2 replaces this ONE function with JWT validation. Nothing else changes.
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
   WRITE (HITL)  — FUTURE: create_employee_record, enroll_social_insurance
                   — MUST require human approval, see Section 6
   COMMUNICATION — FUTURE: notify_finance, send_welcome_email — draft-only
                   by default, see Section 6
   ORCHESTRATION — FUTURE: onboarding checklist/status tools

   Row-level access (_can_access_employee: HR sees all, employee sees only
   self) enforced inside tools via ToolContext today. Mirrored by database
   RLS once Phase 1.5 lands (defense in depth — both layers check).

6. DATA LAYER — PostgreSQL                                  [EXISTS, needs RLS]
   tenant_id on every table, every query. DataSource abstraction
   (mock.py reads Postgres today; odoo.py later, same interface).
   NOTE: "MockDataSource" is a misnomer — it hits a real PostgreSQL DB.
   Rename to PostgreSQLDataSource in Phase 1.5 cleanup.
   FUTURE: RLS with FORCE, per-tenant database option for premium clients,
   field-level encryption for national_id/salary (blind index pattern).

7. KNOWLEDGE / RAG LAYER                                    [NOT BUILT — Phase 3]
   pgvector, co-located with the relational DB (inherits RLS).
   Every chunk carries: tenant_id + allowed_roles + owner_employee_id.
   Retrieval filters on this metadata BEFORE semantic search — never after
   (this is the lesson from the EchoLeak/Copilot failures — see Section 6).
   Labeling: tool-generated documents are auto-tagged by document TYPE
   (each type = allowed_roles + template, same idea as a "batch class" in
   Fotopia's capture/DigitizeMe product — see Section 8 for that mapping).
   Client-uploaded documents: human-classified, fail-CLOSED (most
   restrictive label) if unclassified.
   Tier 1 (public/legal reference data) — separate shared table, no
   tenant_id, no RLS, same for every tenant.

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


PARALLEL — STATEFUL WORKFLOW LAYER                          [NOT BUILT — Phase 2/3]
   New tables: onboarding_cases, onboarding_tasks, pending_actions,
   onboarding_documents (all tenant_id-scoped). Tracks multi-day processes
   that pause for human approval between tool calls. The LangGraph state
   machine (layer 3) reads/writes these.


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
| RAG (future) | Metadata pre-filter (tenant_id + allowed_roles) BEFORE semantic search | The EchoLeak/Copilot lesson — filtering after search is too late |
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
| **1.5** 🔲 next | CI guardrail: automated test asserting RLS is enabled+forced on every `tenant_id` table, plus a cross-tenant/cross-role query test expecting zero rows. Rename MockDataSource → PostgreSQLDataSource. Move session history note to Phase 2 Redis item. Add this BEFORE more tools, not after. |
| **2** 🔲 | JWT auth (replaces `build_context()` stub) — prerequisite for all privileged writes |
| **2** 🔲 | RLS enabled with FORCE + role/field RESTRICTIVE policies (Tier 3) |
| **2** 🔲 | Redis for session history (replaces in-memory _sessions dict) |
| **2** 🔲 | Onboarding Phase 1: document-gen tools only (offer letter, bilingual employment contract, NDA, checklist) — no writes yet |
| **2** 🔲 | ZDR agreement with Anthropic — pursue in parallel with open item #1 below |
| **3** 🔲 | Onboarding Phase 2: `onboarding_cases` state machine + `pending_actions` approval queue + gated writes (Rule 12) |
| **3** 🔲 | RAG/knowledge layer — pgvector, metadata pre-filter, Tier 1/2/3 separation (Rule 14) |
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
