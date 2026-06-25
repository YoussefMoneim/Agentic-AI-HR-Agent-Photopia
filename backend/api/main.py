import asyncio
import logging
import uuid as _uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Header, HTTPException, Query
from typing import Literal
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

    from services.email_listener import run_email_listener
    _listener_task = asyncio.create_task(
        run_email_listener(_data_source, _fotopia_tenant_id),
        name="imap-email-listener",
    )

    yield

    _listener_task.cancel()
    try:
        await _listener_task
    except asyncio.CancelledError:
        pass


app = FastAPI(title="Fotopia HR Agent", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173", "http://localhost:5174", "http://127.0.0.1:5174"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class LoginRequest(BaseModel):
    email: str
    password: str


class LoginResponse(BaseModel):
    access_token: str
    token_type: str
    role: str
    display_name: str
    employee_code: str


class ChatRequest(BaseModel):
    message: str
    session_id: str | None = None
    # TESTING ONLY — ignored when a valid JWT is present. Remove before production.
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


@app.get("/api/me")
def whoami(authorization: str | None = Header(default=None)):
    """Return the authenticated caller's identity. Useful for testing auth without hitting the LLM."""
    ctx = _build_context(authorization, None)
    return {
        "user_id": ctx.user_id,
        "role": ctx.role,
        "employee_code": ctx.employee_code,
        "display_name": ctx.display_name,
    }


@app.post("/auth/login", response_model=LoginResponse)
def login(body: LoginRequest):
    """Issue a JWT for valid credentials. The token encodes role + identity."""
    if _data_source is None:
        raise HTTPException(status_code=503, detail="Service not ready")

    import psycopg2
    conn = psycopg2.connect(config.DATABASE_URL)
    try:
        with conn.cursor() as cur:
            cur.execute("SET app.current_tenant_id = %s", (_fotopia_tenant_id,))
            cur.execute(
                """
                SELECT u.id, u.full_name, u.role, u.password_hash, e.employee_code
                FROM users u
                LEFT JOIN employees e ON e.id = u.employee_id
                WHERE u.tenant_id = %s AND u.email = %s
                """,
                (_fotopia_tenant_id, body.email.lower().strip()),
            )
            row = cur.fetchone()
    finally:
        conn.close()

    if not row:
        raise HTTPException(status_code=401, detail="Invalid email or password")

    user_id, full_name, role, password_hash, employee_code = row

    if not password_hash:
        raise HTTPException(status_code=401, detail="Account not configured for password login")

    from core.auth import AuthError, issue_jwt, verify_password
    if not verify_password(body.password, password_hash):
        raise HTTPException(status_code=401, detail="Invalid email or password")

    token = issue_jwt(
        user_id=str(user_id),
        role=role,
        tenant_id=_fotopia_tenant_id,
        employee_code=employee_code or "",
        display_name=full_name,
    )
    return LoginResponse(
        access_token=token,
        token_type="bearer",
        role=role,
        display_name=full_name,
        employee_code=employee_code or "",
    )


def _build_context(authorization: str | None, demo_role_override: str | None) -> ToolContext:
    """
    Build ToolContext from JWT (primary) or demo_role fallback (DEBUG only).
    JWT path: Authorization: Bearer <token> header — validated, tenant-checked.
    Fallback: demo_role in request body, only when DEBUG_ALLOW_DEMO_ROLE=true.
    """
    if authorization and authorization.startswith("Bearer "):
        token = authorization.split(" ", 1)[1]
        from core.auth import AuthError, decode_context
        try:
            return decode_context(token, _fotopia_tenant_id)
        except AuthError as exc:
            raise HTTPException(status_code=401, detail=str(exc))

    if config.DEBUG_ALLOW_DEMO_ROLE:
        role = demo_role_override if demo_role_override in ("employee", "hr_manager") else config.DEMO_ROLE
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

    raise HTTPException(status_code=401, detail="Authentication required")


@app.post("/chat", response_model=ChatResponse)
def chat(body: ChatRequest, authorization: str | None = Header(default=None)):
    ctx = _build_context(authorization, body.demo_role)
    session_id = body.session_id or str(_uuid.uuid4())
    prior_messages = _sessions.get(session_id, [])

    result = orchestrator.run(body.message, ctx, _llm, _registry, prior_messages=prior_messages)

    _sessions[session_id] = result.messages

    return ChatResponse(
        response=result.text,
        documents=[DocumentInfo(**d) for d in result.documents],
        session_id=session_id,
    )


# STEP 7 — EMAIL LISTENER HOOK
# Phase 2: when the HR Manager inbox is connected, inbound email replies will
# be parsed for the correlation_token embedded in the approve/reject URL and
# routed here programmatically. The outbound_message_id in pending_actions
# stores the SMTP Message-ID so In-Reply-To headers can also resolve the action.
# No JWT required — correlation_token is the sole auth for this endpoint.
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


class SimulateInboundRequest(BaseModel):
    from_email: str
    in_reply_to: str | None = None
    body_text: str


@app.post("/api/email/simulate-inbound")
def simulate_inbound_email(
    body: SimulateInboundRequest,
    authorization: str | None = Header(default=None),
):
    """Simulate an inbound email reply for testing / demo.
    Requires hr_manager or admin role. Calls the same process_inbound_email()
    that the IMAP listener uses — one resolution path, not two.
    """
    if _data_source is None or not _fotopia_tenant_id:
        raise HTTPException(status_code=503, detail="Service not ready")

    ctx = _build_context(authorization, None)
    if ctx.role not in ("hr_manager", "admin"):
        raise HTTPException(status_code=403, detail="Access denied")

    if "@" not in body.from_email:
        raise HTTPException(status_code=422, detail="from_email must contain @")
    if body.in_reply_to is not None and not (
        body.in_reply_to.startswith("<") and body.in_reply_to.endswith(">")
    ):
        raise HTTPException(
            status_code=422,
            detail="in_reply_to must be angle-bracket-wrapped, e.g. <uuid@domain>",
        )

    from services.email_listener import process_inbound_email
    result = process_inbound_email(
        ds=_data_source,
        tenant_id=_fotopia_tenant_id,
        from_email=body.from_email,
        in_reply_to=body.in_reply_to,
        body_text=body.body_text,
    )

    if result.get("error") == "sender_not_authorised":
        raise HTTPException(status_code=403, detail="Sender not authorised for this action")

    return result


@app.get("/api/leave/pending-count")
def get_leave_pending_count():
    if not _fotopia_tenant_id:
        raise HTTPException(status_code=503, detail="Service not ready")
    import psycopg2
    conn = psycopg2.connect(config.DATABASE_URL)
    try:
        with conn.cursor() as cur:
            cur.execute("SET app.current_tenant_id = %s", (_fotopia_tenant_id,))
            cur.execute(
                "SELECT COUNT(*) FROM leave_requests WHERE tenant_id = %s AND status = 'pending_approval'",
                (_fotopia_tenant_id,),
            )
            count = cur.fetchone()[0]
        return {"count": count}
    finally:
        conn.close()


class ApproveBody(BaseModel):
    comment: str | None = None


class RejectBody(BaseModel):
    comment: str


@app.get("/api/leave/pending-approvals-queue")
def get_pending_approvals_queue(authorization: str | None = Header(default=None)):
    """Return pending leave requests for the HR approval inbox UI."""
    if not _fotopia_tenant_id or not _data_source:
        raise HTTPException(status_code=503, detail="Service not ready")
    ctx = _build_context(authorization, None)
    if ctx.role not in ("hr_staff", "hr_manager", "admin"):
        raise HTTPException(status_code=403, detail="Access denied")
    items = _data_source.get_pending_approvals(_fotopia_tenant_id, ctx.employee_code)
    return {"items": items, "count": len(items)}


@app.post("/api/leave/{request_id}/approve")
def approve_leave_via_inbox(
    request_id: str,
    body: ApproveBody,
    authorization: str | None = Header(default=None),
):
    """Approve a leave request from the UI inbox. Routes through ToolRegistry for audit."""
    if not _registry or not _fotopia_tenant_id:
        raise HTTPException(status_code=503, detail="Service not ready")
    ctx = _build_context(authorization, None)
    result = _registry.execute(
        "approve_leave_request",
        {"request_id": request_id, "comment": body.comment},
        ctx,
    )
    if not result.success:
        raise HTTPException(status_code=400, detail=result.error)
    return result.data


@app.post("/api/leave/{request_id}/reject")
def reject_leave_via_inbox(
    request_id: str,
    body: RejectBody,
    authorization: str | None = Header(default=None),
):
    """Reject a leave request from the UI inbox. Routes through ToolRegistry for audit."""
    if not _registry or not _fotopia_tenant_id:
        raise HTTPException(status_code=503, detail="Service not ready")
    ctx = _build_context(authorization, None)
    result = _registry.execute(
        "reject_leave_request",
        {"request_id": request_id, "comment": body.comment},
        ctx,
    )
    if not result.success:
        raise HTTPException(status_code=400, detail=result.error)
    return result.data


@app.get("/api/audit-log")
def get_audit_log(limit: int = Query(default=15, ge=1, le=50)):
    if not _fotopia_tenant_id:
        raise HTTPException(status_code=503, detail="Service not ready")
    import psycopg2
    conn = psycopg2.connect(config.DATABASE_URL)
    try:
        with conn.cursor() as cur:
            cur.execute("SET app.current_tenant_id = %s", (_fotopia_tenant_id,))
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


class AppropriatenessDecisionBody(BaseModel):
    decision: Literal["proceeded", "cancelled"]


@app.post("/api/appropriateness/{event_id}/decision")
def record_appropriateness_decision(
    event_id: str,
    body: AppropriatenessDecisionBody,
    authorization: str | None = Header(default=None),
):
    """Record whether the human proceeded or cancelled after an appropriateness flag."""
    if not _data_source or not _fotopia_tenant_id:
        raise HTTPException(status_code=503, detail="Service not ready")
    # Whitelist event_id characters (UUID hex + hyphens)
    if not all(c in "0123456789abcdefABCDEF-" for c in event_id):
        raise HTTPException(status_code=400, detail="Invalid event ID")
    _build_context(authorization, None)  # auth check — raises 401 if unauthenticated
    _data_source.record_appropriateness_decision(_fotopia_tenant_id, event_id, body.decision)
    return {"ok": True}


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
