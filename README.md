# Fotopia HR Agent

An enterprise SaaS AI agent platform that automates HR tasks for Fotopia Technologies' clients (banks, government bodies, healthcare organizations) across Egypt and the MENA region. The agent is powered by Claude (Anthropic) and built on a strict security-first architecture designed for regulated industries.

---

## What it does

A chat-first HR assistant that lets HR managers and employees get things done without navigating legacy systems. The agent understands natural language, calls the right tools, audits every action, and never invents numbers or document content.

**Current capabilities:**

| Category | Tools |
|---|---|
| Employee data | Read profile, search, list employees, full summary with years-of-service |
| Leave management | Check balance, submit request, approve/reject via chat or email, cancel, view queue |
| Document generation | Salary certificate, To-Whom-It-May-Concern letter, Experience certificate (bilingual, fpdf) |
| Calculations | End-of-service gratuity (Egyptian Labor Law, deterministic Python — never the LLM) |
| Document library | Upload/paste documents, content sensitivity scanning, HITL share-approval flow |
| Audit trail | Every tool call, sensitivity flag, and human share decision is logged with actor identity |

---

## Architecture

```
React frontend  →  FastAPI  →  ToolRegistry (security gateway)  →  Tools  →  PostgreSQL
                                      ↑
                               ToolContext (tenant_id, user_id, role, employee_code)
                                      ↑
                               JWT auth (build_context)
```

**Core security principles:**

- **Policy before prompt** — `ToolRegistry` filters the tool list by role *before* the LLM call. Claude never sees tools it cannot use.
- **Double-check at execution** — `ToolRegistry.execute()` re-validates role at call time, then audits the result.
- **Row-level access** — HR roles see all employees; an employee sees only their own record. Enforced in every tool via `ToolContext`.
- **Deterministic math** — All salary/gratuity calculations are pure Python. The LLM never does arithmetic.
- **LLM-free document content** — fpdf templates are hardcoded; content is slot-filled from the database. The LLM never invents document text.
- **Audit everything** — Every tool call, appropriateness flag, and human share decision is written to `audit_log` and `workflow_events`, never bypassed.

---

## Document sensitivity scanner (added this release)

Demonstrates the platform's content-awareness layer, which will back the RAG/knowledge layer in Phase 3.

**How it works:**

1. **Upload or paste** any document (PDF, DOCX, TXT, or pasted text) into the Document Library tab.
2. **Regex scan** — deterministic patterns flag salary figures, national IDs, medical data, performance reviews, and financial data.
3. **LLM verification** — only the 200-character context window around each match is sent to `claude-haiku-4-5` to filter false positives (e.g. "EGP 850 team lunch" vs "Basic salary EGP 25,000"). Fails closed — if the LLM is unavailable, the content is treated as sensitive.
4. **Share flow** — click Share on any document, pick a recipient from the people-picker (like SharePoint/OneDrive), and the system checks whether the content is appropriate for that recipient's role.
5. **HITL decision** — if a flag fires, the user sees the reason and must explicitly choose to proceed or cancel. Either way, the decision is logged in the Audit Log tab with the actor's name and timestamp.

**What this proves for enterprise customers:**

- The system scans *content*, not labels — it catches a salary figure in a document that was uploaded without any classification.
- The LLM is used only for verification on a minimal excerpt, never for the access-control decision itself.
- Every human override is auditable with identity and timestamp.
- The flag is never a block — HITL means the human always has the final word.

---

## Role model

| Role | What they can do |
|---|---|
| `employee` | Check own leave balance, submit leave, view own documents |
| `hr_staff` | All of the above for any employee + read-only tools |
| `hr_manager` | All tools including document generation and leave approval |
| `admin` | Full access |

Row-level enforcement: `_can_access_employee()` inside every tool — HR roles see everyone, an employee sees only their own record.

---

## Running locally

```bash
cp .env.example .env          # add ANTHROPIC_API_KEY
docker compose up             # starts Postgres + FastAPI (schema + seed auto-load)
curl localhost:8000/health

# Frontend
cd frontend && npm install && npm run dev   # http://localhost:5173

# Talk to the agent
curl -X POST localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"message":"Generate a salary certificate for Saif Ahmed for bank account opening"}'

# Watch the audit log live
watch -n 2 'docker exec fotopia-hr-agent-db-1 psql -U fotopia -d fotopia_hr \
  -c "SELECT tool_name, actor_role, outcome, result_summary, created_at \
      FROM audit_log ORDER BY created_at DESC LIMIT 10;"'
```

**Demo accounts (development only):**

| Name | Email | Password | Role |
|---|---|---|---|
| Nourhan Hosny | hr.agent.fotopia@gmail.com | demo123 | HR Manager |
| Saif Ahmed Hassan | saif.hassan@fotopia.ai | demo123 | Employee |
| Omar Alsayed | omar.alsayed@fotopia.ai | demo123 | Employee |

---

## Tech stack

| Layer | Choice |
|---|---|
| LLM | Claude Sonnet 4.5 (Anthropic SDK, swappable via `LLM_PROVIDER` env var) |
| Backend | Python 3.11, FastAPI, psycopg2 |
| Database | PostgreSQL 15 with per-tenant RLS |
| Document gen | fpdf2 |
| Frontend | React 18, Vite |
| Auth | JWT (HS256), bcrypt |
| Containers | Docker Compose |

---

## What's next

- **Phase 1.5** — CI guardrail asserting RLS is enabled and forced on every tenant table; rename `MockDataSource` → `PostgreSQLDataSource`
- **Phase 2** — Redis session history, real JWT replace the `build_context()` stub, onboarding document-gen tools
- **Phase 3** — pgvector RAG with metadata pre-filter (tenant_id + allowed_roles before semantic search), audit log hash-chaining + WORM mirror
- **Phase 4** — "Jarvis" proactive layer: daily briefing → goal tracking → assisted execution

---

## Team

- **Youssef (Joe) Abdelmoneim** — Engineering (Computer Engineering, AUS, AI/ML intern)
- **Dr. Ahmed El-Yazbi** — R&D AI Director, technical stakeholder
- **Raef Eid** — Founder / chief software architect
- **Nourhan Hosny** — HR Project Lead, first pilot user
- **Fotopia Technologies** — Cairo, under WIN Holding Group
