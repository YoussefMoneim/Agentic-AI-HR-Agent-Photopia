# Fotopia HR Agent

**Enterprise AI operations platform — HR module — WIN Holding Group pilot**

> "Enterprise Intelligence. Agentic Work. Governed Execution." — Raef Eid, CEO Fotopia Technologies

---

## What It Is

The Fotopia HR Agent is a production-grade AI system that automates the full HR operations lifecycle for enterprise clients. It is the first module of **Zumra** — Fotopia's broader enterprise AI platform — and serves as the proof of concept for an agentic shared-services architecture that mirrors how companies actually work.

Employees interact with it in plain Arabic or English through a chat interface or email. The system understands their request, validates it against the company's leave policy, routes it to the right manager for approval, syncs with the ERP automatically, and notifies everyone involved. Every action is audited. Nothing changes without a human decision.

Built during the Fotopia 2026 internship. Demonstrated to CEO Raef Eid and WIN Holding Group on July 5, 2026.

---

## Current Status

**296 tests passing. 0 failures.**

| Layer | Status |
|---|---|
| Executor (leave lifecycle, email agent, Odoo sync, audit trail) | ✅ Complete |
| Vector knowledge base (semantic policy search, Arabic + English) | ✅ Complete |
| SharePoint auto-sync connector | 🔄 In progress |
| Email thread context memory | 🔄 In progress |

---

## What It Does

### Leave Management (18 Leave Types)
- Submit leave via chat or email in natural language
- Full WIN Holding policy enforcement: notice periods, service minimums, career caps, department concurrent limits (25%), probation checks
- Retroactive submission allowed for sick/emergency/funeral (UAE labor law compliant)
- Manager approval via one-click email link, email reply, or approval inbox UI
- Leave cancellation flow with manager approval
- Egypt work week (Sun–Thu) with public holiday exclusions

### Email Agent (Bidirectional)
- Employees email `hr.agent.fotopia@gmail.com` directly
- Claude Haiku classifies intent with confidence scoring
- Natural language date extraction ("first two weeks of August")
- Auto-reply with policy-compliant response in ~15 seconds
- Rate limited: 10 requests/hour per employee

### Odoo ERP Integration
- Approved leave auto-creates `hr.leave` record in Odoo 16
- Cancelled leave deleted via refuse → draft → unlink sequence
- Non-blocking: Odoo failures never block approvals
- Protocol: XML-RPC (built-in, no paid API required)

### Notifications
- Submission confirmation email to employee
- Branded manager approval email with one-click Approve/Reject
- Branded decision email to employee (✅/❌)
- HR notification with compliance checklist and TimeLOG action items
- All paths produce identical branded templates regardless of submission channel

### Vector Knowledge Base (Feeder Agent)
- **voyage-multilingual-2** embeddings (1024 dimensions, Arabic + English)
- pgvector on PostgreSQL — same database, no additional infrastructure
- Hybrid search: vector similarity + full-text fallback (never breaks)
- 95 chunks ingested from WIN Holding policy documents
- Cross-lingual retrieval confirmed: Arabic query → correct English policy section
- Access control: `allowed_roles[]` enforced in SQL pre-filter (not post-filter)
- Graceful degradation on Voyage AI API failure

### Document & HR Tools
- Salary certificate generation (branded PDF)
- Experience certificate generation
- Document sensitivity scanning (OCR + LLM verification on excerpt only)
- Team calendar view
- Excel export: Leave Register, Balance Summary, Monthly Summary
- Sick leave abuse detection
- Documentation gate before submitting high-sensitivity leave types

---

## Architecture
DESIGN LAYER (Feeder Agent)
Policy documents (PDF/MD)
↓ ingest_policies.py
Voyage AI voyage-multilingual-2
↓ 1024-dim embeddings
pgvector (private_document_chunks)
↓ KnowledgeBase.search()
EXECUTOR LAYER (HR Agent)
Employee (Chat UI / Email)
↓ Natural language
FastAPI Backend  →  JWT auth
↓
Claude Sonnet 4.5  →  Tool selection
↓
Constraint Engine  →  Policy enforcement (deterministic Python)
↓
PostgreSQL (RLS FORCE)  →  Leave request stored
↓
Office 365 SMTP  →  Manager notified
↓
Manager approves (email / UI)
↓
Odoo 16 (XML-RPC)  →  ERP updated
↓
Audit Log  →  Every step recorded

### Security Model

Three independent enforcement layers — all must pass for any write action:

1. **API route** — JWT HS256 validated, role extracted from token claims
2. **Tool registry** — Role checked against `tool.spec.allowed_roles` before execution. Denied attempts audited.
3. **Database RLS** — PostgreSQL `FORCE ROW LEVEL SECURITY` on every tenant table. Bypassed by nothing.

| Role | Access |
|---|---|
| `employee` | Own data only |
| `hr_staff` | Team data, read-only tools |
| `hr_manager` | Full HR access, approve/reject, export, ingest documents |
| `admin` | System admin, all access |

---

## Tech Stack

| Component | Technology |
|---|---|
| Frontend | React 18 + Vite 5.x, TypeScript, Tailwind CSS |
| Backend | FastAPI 0.115.x, Python 3.11, Uvicorn |
| Database | PostgreSQL 15 with pgvector 0.8.3 |
| AI Model (Chat) | Claude Sonnet 4.5 (Anthropic) |
| AI Model (Email) | Claude Haiku 4.5 |
| Embeddings | Voyage AI voyage-multilingual-2 (1024 dims) |
| Agent Framework | LangGraph |
| ERP | Odoo 16 via XML-RPC |
| Email Send | Office 365 SMTP |
| Email Receive | Gmail IMAP |
| Containers | Docker Compose 2.x |
| Auth | JWT HS256 + bcrypt |
| Testing | pytest — 296 tests, 0 failures |

---

## Running Locally

```bash
# Clone
git clone https://github.com/YoussefMoneim/Agentic-AI-HR-Agent-Photopia.git
cd Agentic-AI-HR-Agent-Photopia

# Add .env file (obtain from team — not in repo)

# Build and start
docker compose build backend
docker compose up -d

# Frontend
cd frontend && npm install && npm run dev
# → http://localhost:5173

# Seed vector knowledge base (once after setup)
docker exec fotopia-hr-agent-backend-1 python /app/scripts/ingest_policies.py

# Run tests
docker exec fotopia-hr-agent-backend-1 python -m pytest tests/ -q
# Expected: 296 passed, 0 failed

# Demo reset (before any demo)
docker exec fotopia-hr-agent-backend-1 python /app/scripts/demo_reset.py
```

---

## Demo Accounts

| Name | Email | Password | Role |
|---|---|---|---|
| Youssef Abdelmoneim | i-youssef.abdelmoneim@fotopiatech.com | demo123 | Employee |
| Saif Ahmed | i-saif.ahmed@fotopiatech.com | demo123 | Employee |
| Noura Al Rashidi | noura.rashidi@fotopiatech.com | demo123 | HR Manager |
| Khalid Al Hashmi | khalid.hashmi@fotopiatech.com | demo123 | Manager |

**HR Inbox:** hr.agent.fotopia@gmail.com  
**System email:** fotoagent@fotopiatech.com  
**Odoo staging:** winholding-erp-winholding-stage-34182670.dev.odoo.com

---

## Roadmap

| Block | Status | Description |
|---|---|---|
| 0 — Executor Layer | ✅ Complete | Full HR agent, leave lifecycle, email agent, Odoo sync |
| 1 — Feeder Agent Phase 1 | ✅ Complete | Vector knowledge base, semantic search, policy ingestion |
| 2 — External Auto-Sync | 🔄 In Progress | SharePoint connector, email thread memory |
| 3 — Agent Memory & Autonomy | 📋 Planned | Short/long-term memory, ReAct tool selection |
| 4 — Five-File Agent Structure | 📋 Planned | Identity, role, skills, scheduler, memory |
| 5 — Second Agent | 📋 Planned | Finance agent — proves architecture generalizes |
| 6 — DigitizeMe Integration | 📋 Planned | Auto-sync from Fotopia content platform |
| 7 — Production Hardening | 📋 Planned | Azure AI Search, Nuxeo, M365 OAuth2 |

---

## Team

| Person | Role |
|---|---|
| Youssef Abdelmoneim | AI Engineering Intern — Computer Engineering, AUS 2027 |
| Saif Ahmed | AI Engineering Intern — Computer Engineering, University of Sharjah |
| Dr. Ahmed El-Yazbi | Technical Supervisor — Fotopia Technologies |
| Raef Eid | CEO — Fotopia Technologies / WIN Holding Group |

**Organization:** Fotopia Technologies — WIN Holding Group  
**Pilot client:** WIN Holding Group  
**Started:** June 2026 | **Demo:** July 5, 2026
