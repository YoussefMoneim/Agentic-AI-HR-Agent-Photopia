import logging
import uuid as _uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel

import config
from agent import orchestrator
from audit.logger import AuditLogger
from data.base import DataSource
from data.factory import get_data_source
from llm.factory import get_llm
from services import email as email_svc
from tools.base import ToolContext
from tools.registry import ToolRegistry, build_registry

logging.basicConfig(level=logging.INFO)


class _SuppressPollLog(logging.Filter):
    def filter(self, record):
        msg = record.getMessage()
        return '/api/audit-log' not in msg and '/api/leave/pending-count' not in msg


logging.getLogger("uvicorn.access").addFilter(_SuppressPollLog())

_llm = None
_registry = None
_data_source: DataSource | None = None
_fotopia_tenant_id: str = ""
_sessions: dict[str, list[dict]] = {}  # session_id → raw messages list


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _llm, _registry, _data_source, _fotopia_tenant_id

    _llm = get_llm()
    _data_source = get_data_source()
    audit_logger = AuditLogger(config.DATABASE_URL)

    import psycopg2
    conn = psycopg2.connect(config.DATABASE_URL)
    with conn.cursor() as cur:
        cur.execute("SELECT id FROM tenants WHERE slug = %s", (config.TENANT_SLUG,))
        row = cur.fetchone()
        if row is None:
            raise RuntimeError(f"Tenant '{config.TENANT_SLUG}' not found in database. Did you run seed.sql?")
        _fotopia_tenant_id = str(row[0])
    conn.close()

    _registry = build_registry(_data_source, audit_logger)
    yield


app = FastAPI(title="Fotopia HR Agent", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173", "http://localhost:5174", "http://127.0.0.1:5174"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class ChatRequest(BaseModel):
    message: str
    session_id: str | None = None
    # TESTING ONLY — remove before production. Allows switching identities without restarting Docker.
    demo_role: str | None = None


class DocumentInfo(BaseModel):
    id: str
    type: str
    employee_name: str


class ChatResponse(BaseModel):
    response: str
    documents: list[DocumentInfo]
    session_id: str


@app.get("/health")
def health():
    return {"status": "ok", "tenant": config.TENANT_SLUG, "llm_provider": config.LLM_PROVIDER}


def _build_context(role_override: str | None = None) -> ToolContext:
    """Phase 1 stub. Phase 2: decode JWT, look up user in DB, populate from their record.
    Switch identity via DEMO_ROLE env var or the demo_role request field (TESTING ONLY):
      employee   → EMP001 Saif Ahmed Hassan
      hr_manager → EMP002 Nourhan Hosny (default)
    """
    role = role_override if role_override in ("employee", "hr_manager") else config.DEMO_ROLE
    if role == "employee":
        return ToolContext(
            tenant_id=_fotopia_tenant_id,
            user_id="demo-employee",
            role="employee",
            employee_code="EMP001",
            display_name="Saif Ahmed Hassan",
        )
    return ToolContext(
        tenant_id=_fotopia_tenant_id,
        user_id="demo-user",
        role="hr_manager",
        employee_code="EMP002",
        display_name="Nourhan Hosny",
    )


@app.post("/chat", response_model=ChatResponse)
def chat(body: ChatRequest):
    ctx = _build_context(body.demo_role)
    session_id = body.session_id or str(_uuid.uuid4())
    prior_messages = _sessions.get(session_id, [])

    result = orchestrator.run(body.message, ctx, _llm, _registry, prior_messages=prior_messages)

    _sessions[session_id] = result.messages

    return ChatResponse(
        response=result.text,
        documents=[DocumentInfo(**d) for d in result.documents],
        session_id=session_id,
    )


@app.get("/api/leave/resolve/{correlation_token}", response_class=HTMLResponse)
def resolve_leave_request(
    correlation_token: str,
    decision: str = Query(..., pattern="^(approved|rejected)$"),
):
    """
    Email approval link handler. Manager clicks Approve/Reject in the email;
    this endpoint resolves the pending action and returns a simple HTML confirmation page.
    The correlation_token is the authentication mechanism — keep it long and unguessable (UUID v4).
    """
    if _data_source is None:
        raise HTTPException(status_code=503, detail="Service not ready")

    # Whitelist token characters (UUID format: hex + hyphens)
    if not all(c in "0123456789abcdefABCDEF-" for c in correlation_token):
        raise HTTPException(status_code=400, detail="Invalid token format")

    result = _data_source.resolve_pending_action(
        tenant_id=_fotopia_tenant_id,
        correlation_token=correlation_token,
        decision=decision,
        resolved_by_code=None,  # resolved via email link — actor identity is the token itself
        note=f"Resolved via email approval link (decision: {decision})",
    )

    if not result.get("success"):
        error_msg = result.get("error", "Could not process this request.")
        return HTMLResponse(
            content=f"""
            <html><body style="font-family:sans-serif;max-width:500px;margin:60px auto;text-align:center">
            <h2>⚠️ Unable to Process Request</h2>
            <p>{error_msg}</p>
            <p>The request may have already been resolved, or the link has expired.</p>
            </body></html>
            """,
            status_code=409,
        )

    employee_code = result.get("employee_code", "")
    days = result.get("days_requested", 0)
    action_word = "approved ✅" if decision == "approved" else "rejected ❌"

    # Send confirmation email to the employee
    if employee_code and _data_source:
        emp = _data_source.get_employee_by_code(_fotopia_tenant_id, employee_code)
        if emp and emp.get("email"):
            status_word = "approved" if decision == "approved" else "rejected"
            email_svc.send_email(
                to_email=emp["email"],
                subject=f"Leave Request {status_word.capitalize()} — {emp['full_name']}",
                body_html=(
                    f"<p>Your leave request ({days:.0f} days) has been "
                    f"<strong>{status_word}</strong>.</p>"
                ),
                body_plain=f"Your leave request ({days:.0f} days) has been {status_word}.",
            )

    return HTMLResponse(
        content=f"""
        <html><body style="font-family:sans-serif;max-width:500px;margin:60px auto;text-align:center">
        <h2>Leave Request {action_word}</h2>
        <p>The leave request for <strong>{employee_code}</strong>
           ({days:.0f} {'day' if days == 1 else 'days'}) has been <strong>{decision}</strong>.</p>
        <p>The employee has been notified.</p>
        </body></html>
        """,
        status_code=200,
    )


@app.get("/api/leave/pending-count")
def get_leave_pending_count():
    if not _fotopia_tenant_id:
        raise HTTPException(status_code=503, detail="Service not ready")
    import psycopg2
    conn = psycopg2.connect(config.DATABASE_URL)
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT COUNT(*) FROM leave_requests WHERE tenant_id = %s AND status = 'pending_approval'",
                (_fotopia_tenant_id,),
            )
            count = cur.fetchone()[0]
        return {"count": count}
    finally:
        conn.close()


@app.get("/api/audit-log")
def get_audit_log(limit: int = Query(default=15, ge=1, le=50)):
    if not _fotopia_tenant_id:
        raise HTTPException(status_code=503, detail="Service not ready")
    import psycopg2
    conn = psycopg2.connect(config.DATABASE_URL)
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, tool_name, actor_role, action, outcome,
                       result_summary, created_at
                FROM audit_log
                WHERE tenant_id = %s
                ORDER BY created_at DESC
                LIMIT %s
                """,
                (_fotopia_tenant_id, limit),
            )
            cols = ["id", "tool_name", "actor_role", "action", "outcome", "result_summary", "created_at"]
            rows = []
            for row in cur.fetchall():
                r = dict(zip(cols, row))
                r["created_at"] = r["created_at"].isoformat() if r["created_at"] else None
                rows.append(r)
        return {"entries": rows}
    finally:
        conn.close()


@app.get("/documents/{doc_id}")
def get_document(doc_id: str):
    # Whitelist characters to block path traversal (e.g. "../../etc/passwd")
    if not all(c in "0123456789abcdefABCDEF-" for c in doc_id):
        raise HTTPException(status_code=400, detail="Invalid document ID")

    path = Path(config.DOCUMENTS_DIR) / f"{doc_id}.pdf"
    if not path.exists():
        raise HTTPException(status_code=404, detail="Document not found")

    return FileResponse(
        path=str(path),
        media_type="application/pdf",
        filename=f"certificate_{doc_id[:8]}.pdf",
    )
