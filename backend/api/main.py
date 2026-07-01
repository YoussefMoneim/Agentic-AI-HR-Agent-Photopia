import asyncio
import io
import json
import logging
import uuid as _uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal

import psycopg2
from fastapi import FastAPI, File, Header, HTTPException, Query, UploadFile
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
from workflow.constraints import evaluate_constraints

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


@app.get("/api/employees")
def list_employees_for_ui(authorization: str | None = Header(default=None)):
    """Return employees visible to the caller for the people-picker UI."""
    ctx = _build_context(authorization, None)
    conn = psycopg2.connect(config.DATABASE_URL)
    try:
        with conn.cursor() as cur:
            cur.execute("SET ROLE fotopia_app")
            cur.execute("SET app.current_tenant_id = %s", (ctx.tenant_id,))
            cur.execute(
                    """
                    SELECT e.employee_code, e.full_name, COALESCE(u.role, 'employee'),
                           e.department, e.position
                    FROM employees e
                    LEFT JOIN users u ON u.employee_id = e.id AND u.tenant_id = e.tenant_id
                    WHERE e.tenant_id = %s::uuid
                    ORDER BY e.full_name
                    """,
                    (ctx.tenant_id,),
                )
            cols = ["employee_code", "full_name", "role", "department", "position"]
            rows = [dict(zip(cols, row)) for row in cur.fetchall()]
        return {"employees": rows}
    finally:
        conn.close()


@app.post("/auth/login", response_model=LoginResponse)
def login(body: LoginRequest):
    """Issue a JWT for valid credentials. The token encodes role + identity."""
    if _data_source is None:
        raise HTTPException(status_code=503, detail="Service not ready")

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


def _resolve_page(icon: str, title_color: str, title: str, message: str, details: str = "") -> str:
    details_block = (
        f'<div style="background:#f8f8fb;border-radius:6px;padding:14px 20px;'
        f'font-size:13px;color:#444;text-align:left">{details}</div>'
    ) if details else ""
    return f"""<!DOCTYPE html>
<html>
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Fotopia HR System</title></head>
<body style="margin:0;padding:0;background:#f4f4f7;font-family:Arial,sans-serif;min-height:100vh;display:flex;align-items:center;justify-content:center">
  <div style="max-width:480px;width:90%;text-align:center">
    <div style="background:#0a0c1a;padding:20px 30px;border-radius:8px 8px 0 0">
      <div style="color:#fff;font-size:18px;font-weight:bold">Fotopia HR System</div>
      <div style="color:#c9a84c;font-size:12px;margin-top:4px">WIN Holding Group &mdash; HR Portal</div>
    </div>
    <div style="background:#fff;padding:40px 36px;border-radius:0 0 8px 8px;box-shadow:0 4px 20px rgba(0,0,0,0.08)">
      <div style="font-size:48px;margin-bottom:16px">{icon}</div>
      <h2 style="margin:0 0 12px 0;color:{title_color};font-size:22px">{title}</h2>
      <p style="margin:0 0 24px 0;color:#555;font-size:14px;line-height:1.6">{message}</p>
      {details_block}
      <p style="margin:24px 0 0 0;font-size:11px;color:#aaa">You can close this tab. The employee has been notified.</p>
    </div>
    <p style="margin:16px 0 0 0;font-size:11px;color:#999">Fotopia HR System &mdash; Automated action</p>
  </div>
</body>
</html>"""


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

    # Constraint check for approval decisions only — must run BEFORE state change
    if decision == "approved":
        lr_check = _data_source.get_leave_request_by_token(_fotopia_tenant_id, correlation_token)
        if lr_check:  # None = already resolved; let resolve_pending_action() return its own error
            approver_ctx = ToolContext(
                tenant_id=_fotopia_tenant_id,
                user_id=lr_check.get("approver_employee_code", "email_link"),
                role=lr_check.get("approver_role", "hr_manager"),
                employee_code=lr_check.get("approver_employee_code", ""),
            )
            constraint = evaluate_constraints(approver_ctx, "approve_leave", lr_check, _data_source)
            if constraint.verdict == "blocked":
                _emp   = lr_check.get("employee_name", lr_check.get("employee_code", ""))
                _code  = lr_check.get("employee_code", "")
                _type  = lr_check.get("leave_type_name", "")
                _start = lr_check.get("start_date", "")
                _end   = lr_check.get("end_date", "")
                _days  = lr_check.get("days_requested") or 0
                return HTMLResponse(content=_resolve_page(
                    icon="🚫",
                    title_color="#dc2626",
                    title="Approval Not Permitted",
                    message=f"This leave cannot be approved via email link: <strong>{constraint.reason}</strong> No changes were made.",
                    details=f"Employee: {_emp} ({_code}) &nbsp;|&nbsp; Leave: {_type} &nbsp;|&nbsp; {_start} &rarr; {_end} &nbsp;|&nbsp; {_days:.0f} days",
                ), status_code=200)
            if constraint.verdict == "requires_override":
                _emp   = lr_check.get("employee_name", lr_check.get("employee_code", ""))
                _code  = lr_check.get("employee_code", "")
                _type  = lr_check.get("leave_type_name", "")
                _start = lr_check.get("start_date", "")
                _end   = lr_check.get("end_date", "")
                _days  = lr_check.get("days_requested") or 0
                return HTMLResponse(content=_resolve_page(
                    icon="⚠️",
                    title_color="#d97706",
                    title="Additional Review Required",
                    message=f"This approval requires a justification override: <strong>{constraint.reason}</strong>",
                    details=f"Employee: {_emp} ({_code}) &nbsp;|&nbsp; Leave: {_type} &nbsp;|&nbsp; {_start} &rarr; {_end} &nbsp;|&nbsp; {_days:.0f} days<br><br>Please approve from the HR inbox where you can provide an override reason.",
                ), status_code=200)
            # verdict == "allowed" or "advisory": fall through to resolve_pending_action()

    result = _data_source.resolve_pending_action(
        tenant_id=_fotopia_tenant_id,
        correlation_token=correlation_token,
        decision=decision,
        resolved_by_code=None,  # resolved via email link — actor identity is the token itself
        note=f"Resolved via email approval link (decision: {decision})",
    )

    if not result.get("success"):
        error_msg = result.get("error", "Could not process this request.")
        if "Already resolved" in error_msg:
            _status = error_msg.replace("Already resolved: ", "").replace("_", " ").title()
            return HTMLResponse(content=_resolve_page(
                icon="ℹ️",
                title_color="#2563eb",
                title="Already Processed",
                message="This leave request has already been processed. No further action is needed.",
                details=f"Status: {_status}",
            ), status_code=409)
        elif "expired" in error_msg.lower():
            return HTMLResponse(content=_resolve_page(
                icon="⏱️",
                title_color="#d97706",
                title="Link Expired",
                message="This approval link has expired. Please use the HR inbox to process pending requests.",
            ), status_code=409)
        else:
            return HTMLResponse(content=_resolve_page(
                icon="⚠️",
                title_color="#d97706",
                title="Unable to Process Request",
                message=error_msg,
            ), status_code=409)

    employee_code = result.get("employee_code", "")
    days = result.get("days_requested", 0)
    action_word = "approved ✅" if decision == "approved" else "rejected ❌"

    # Send confirmation email to the employee
    if employee_code and _data_source:
        emp = _data_source.get_employee_by_code(_fotopia_tenant_id, employee_code)
        if emp and emp.get("email"):
            status_word = "approved" if decision == "approved" else "rejected"
            email_svc.send_email(
                to_email=emp.get("notification_email") or emp["email"],
                subject=f"Leave Request {status_word.capitalize()} — {emp['full_name']}",
                body_html=(
                    f"<p>Your leave request ({days:.0f} days) has been "
                    f"<strong>{status_word}</strong>.</p>"
                ),
                body_plain=f"Your leave request ({days:.0f} days) has been {status_word}.",
            )

    # Odoo sync for approved leaves — non-blocking
    if decision == "approved" and config.ODOO_ENABLED and _data_source:
        try:
            from services.odoo_sync import sync_approved_leave
            import logging as _logging
            _lr_full = _data_source.get_leave_request_by_id(
                _fotopia_tenant_id, result.get("leave_request_id", "")
            )
            _emp_odoo = _data_source.get_employee_by_code(_fotopia_tenant_id, employee_code) if employee_code else None
            _emp_email = _emp_odoo.get("email") if _emp_odoo else None
            if _lr_full and _emp_email:
                _odoo = sync_approved_leave(
                    employee_email=_emp_email,
                    leave_type_code=_lr_full.get("leave_type_code", ""),
                    start_date=str(_lr_full.get("start_date", "")),
                    end_date=str(_lr_full.get("end_date", "")),
                    reason=_lr_full.get("reason"),
                    our_request_id=result.get("leave_request_id", ""),
                )
                if not _odoo.get("skipped") and not _odoo.get("synced"):
                    _logging.getLogger(__name__).warning(
                        "Odoo sync failed (non-blocking): %s", _odoo.get("error")
                    )
        except Exception as _odoo_err:
            import logging as _logging
            _logging.getLogger(__name__).error("Odoo sync exception (non-blocking): %s", _odoo_err)

    if decision == "approved":
        _icon, _color, _title = "✅", "#16a34a", "Leave Request Approved"
        _msg = "The leave request has been approved. The employee has been notified."
    else:
        _icon, _color, _title = "❌", "#dc2626", "Leave Request Rejected"
        _msg = "The leave request has been rejected. The employee has been notified."
    return HTMLResponse(content=_resolve_page(
        icon=_icon,
        title_color=_color,
        title=_title,
        message=_msg,
        details=f"Employee: {employee_code} &nbsp;|&nbsp; Duration: {days:.0f} {'day' if days == 1 else 'days'}",
    ), status_code=200)


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
    override_reason: str | None = None


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


@app.post("/api/leave/{request_id}/check-constraints")
def check_leave_constraints_endpoint(
    request_id: str,
    authorization: str | None = Header(default=None),
):
    """Read-only constraint preflight for the inbox UI. Returns verdict with no state change."""
    if not _fotopia_tenant_id or not _data_source:
        raise HTTPException(status_code=503, detail="Service not ready")
    ctx = _build_context(authorization, None)
    lr = _data_source.get_leave_request_by_id(_fotopia_tenant_id, request_id)
    if not lr:
        raise HTTPException(status_code=404, detail="Leave request not found")
    constraint = evaluate_constraints(ctx, "approve_leave", lr, _data_source)
    return {
        "verdict": constraint.verdict,
        "reason": constraint.reason,
        "flags": constraint.flags,
        "override_reason_required": constraint.override_reason_required,
    }


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
        {"request_id": request_id, "comment": body.comment, "override_reason": body.override_reason},
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


class RequestCancellationBody(BaseModel):
    reason: str | None = None


class ApproveCancellationBody(BaseModel):
    consumed_days: float | None = None


@app.post("/api/leave/{request_id}/request-cancellation")
def request_leave_cancellation_via_api(
    request_id: str,
    body: RequestCancellationBody,
    authorization: str | None = Header(default=None),
):
    """Submit a cancellation request for an already-approved leave. Any role; own leave only for employees."""
    if not _registry or not _fotopia_tenant_id:
        raise HTTPException(status_code=503, detail="Service not ready")
    ctx = _build_context(authorization, None)
    result = _registry.execute(
        "request_leave_cancellation",
        {"request_id": request_id, "reason": body.reason},
        ctx,
    )
    if not result.success:
        raise HTTPException(status_code=400, detail=result.error)
    return result.data


@app.post("/api/leave/{request_id}/approve-cancellation")
def approve_leave_cancellation_via_api(
    request_id: str,
    body: ApproveCancellationBody,
    authorization: str | None = Header(default=None),
):
    """Approve a pending cancellation and restore the balance. HR only."""
    if not _registry or not _fotopia_tenant_id:
        raise HTTPException(status_code=503, detail="Service not ready")
    ctx = _build_context(authorization, None)
    result = _registry.execute(
        "approve_leave_cancellation",
        {"request_id": request_id, "consumed_days": body.consumed_days},
        ctx,
    )
    if not result.success:
        raise HTTPException(status_code=400, detail=result.error)
    return result.data


@app.get("/api/leave/pending-cancellations")
def get_pending_cancellations_via_api(authorization: str | None = Header(default=None)):
    """Return all leave requests pending HR cancellation approval."""
    if not _registry or not _fotopia_tenant_id:
        raise HTTPException(status_code=503, detail="Service not ready")
    ctx = _build_context(authorization, None)
    result = _registry.execute("get_pending_cancellations", {}, ctx)
    if not result.success:
        raise HTTPException(status_code=403, detail=result.error)
    return result.data


@app.get("/api/calendar/leave")
def get_leave_calendar(
    year: int | None = None,
    month: int | None = None,
    department: str | None = None,
    authorization: str | None = Header(default=None),
):
    """Team leave calendar — role-scoped view of who is on leave for a given month."""
    if not _fotopia_tenant_id or not _data_source:
        raise HTTPException(status_code=503, detail="Service not ready")
    from datetime import date as _date
    ctx = _build_context(authorization, None)
    today = _date.today()
    year  = year  or today.year
    month = month or today.month
    if not (1 <= month <= 12):
        raise HTTPException(status_code=400, detail="month must be 1-12")
    if not (2020 <= year <= 2030):
        raise HTTPException(status_code=400, detail="year must be between 2020 and 2030")
    emp = _data_source.get_employee_by_code(_fotopia_tenant_id, ctx.employee_code)
    caller_employee_id = str(emp["id"]) if emp else None
    result = _data_source.get_team_calendar(
        tenant_id=_fotopia_tenant_id,
        caller_role=ctx.role,
        caller_employee_id=caller_employee_id,
        year=year,
        month=month,
        department=department if ctx.role in ("hr_staff", "hr_manager", "admin") else None,
    )
    result["viewer_role"] = ctx.role
    return result


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
    ctx = _build_context(authorization, None)
    _data_source.record_appropriateness_decision(_fotopia_tenant_id, event_id, body.decision)
    conn = psycopg2.connect(config.DATABASE_URL)
    try:
        with conn.cursor() as cur:
            cur.execute("SET ROLE fotopia_app")
            cur.execute("SET app.current_tenant_id = %s", (ctx.tenant_id,))
            cur.execute(
                """
                INSERT INTO audit_log (tenant_id, actor_user_id, actor_role, tool_name,
                    tool_input, outcome, authz_decision, result_summary, latency_ms, action)
                VALUES (%s, %s, %s, 'share_decision', %s, 'success', 'allowed', %s, 0, 'data_write')
                """,
                (
                    ctx.tenant_id, ctx.user_id, ctx.role,
                    json.dumps({"event_id": event_id, "decision": body.decision}),
                    f"Share decision: {body.decision}",
                ),
            )
        conn.commit()
    finally:
        conn.close()
    return {"ok": True}


def _extract_text_from_upload(filename: str, raw_bytes: bytes) -> str:
    """Extract plain text from PDF, DOCX, or TXT. Falls back to raw UTF-8 decode."""
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    try:
        if ext == "pdf":
            from pypdf import PdfReader
            reader = PdfReader(io.BytesIO(raw_bytes))
            return "\n".join(page.extract_text() or "" for page in reader.pages)
        if ext in ("docx", "doc"):
            import docx
            doc = docx.Document(io.BytesIO(raw_bytes))
            return "\n".join(p.text for p in doc.paragraphs)
    except Exception:
        pass
    return raw_bytes.decode("utf-8", errors="replace")


class PasteDocRequest(BaseModel):
    content: str
    filename: str = "pasted-text.txt"


def _scan_and_store_demo_doc(
    ctx,
    filename: str,
    content_text: str,
    file_size_bytes: int,
) -> dict:
    """Shared logic: scan content, store in demo_documents, return result."""
    from workflow.appropriateness import scan_content_for_sensitivity, verify_sensitivity_with_llm, extract_surrounding_context

    scan = scan_content_for_sensitivity(content_text)
    is_sensitive = bool(scan)

    # LLM verification on first match per type
    enriched_scan: dict = {}
    for stype, examples in scan.items():
        entry: dict = {"examples": examples}
        if examples and _llm is not None:
            context = extract_surrounding_context(content_text, examples[0])
            verdict = verify_sensitivity_with_llm(stype, context, _llm)
            entry["llm_verdict"] = verdict
            if not verdict.get("is_sensitive", True):
                entry["confirmed_false_positive"] = True
        enriched_scan[stype] = entry

    conn = psycopg2.connect(config.DATABASE_URL)
    try:
        with conn.cursor() as cur:
            cur.execute("SET ROLE fotopia_app")
            cur.execute("SET app.current_tenant_id = %s", (ctx.tenant_id,))
            cur.execute(
                """
                INSERT INTO demo_documents
                    (tenant_id, uploaded_by, filename, content_text,
                     file_size_bytes, sensitivity_scan, is_sensitive)
                VALUES (%s::uuid, %s, %s, %s, %s, %s, %s)
                RETURNING id, created_at
                """,
                (
                    ctx.tenant_id, ctx.user_id, filename, content_text,
                    file_size_bytes, json.dumps(enriched_scan), is_sensitive,
                ),
            )
            doc_id, created_at = cur.fetchone()
        conn.commit()
    finally:
        conn.close()

    return {
        "id": str(doc_id),
        "filename": filename,
        "is_sensitive": is_sensitive,
        "sensitivity_types": list(scan.keys()),
        "sensitivity_scan": enriched_scan,
        "created_at": created_at.isoformat(),
    }


@app.post("/api/documents/upload-demo")
async def upload_demo_document(
    file: UploadFile = File(...),
    authorization: str | None = Header(default=None),
):
    """Upload a file (PDF/DOCX/TXT), scan its content for sensitivity."""
    if not _data_source or not _fotopia_tenant_id:
        raise HTTPException(status_code=503, detail="Service not ready")
    ctx = _build_context(authorization, None)
    raw = await file.read()
    content_text = _extract_text_from_upload(file.filename or "upload.txt", raw)
    return _scan_and_store_demo_doc(ctx, file.filename or "upload.txt", content_text, len(raw))


@app.post("/api/documents/paste-demo")
def paste_demo_document(
    body: PasteDocRequest,
    authorization: str | None = Header(default=None),
):
    """Accept pasted plain text, scan for sensitivity — no file upload needed."""
    if not _data_source or not _fotopia_tenant_id:
        raise HTTPException(status_code=503, detail="Service not ready")
    ctx = _build_context(authorization, None)
    return _scan_and_store_demo_doc(ctx, body.filename, body.content, len(body.content.encode()))


@app.get("/api/documents/demo")
def get_demo_documents(authorization: str | None = Header(default=None)):
    """Return demo documents uploaded by the current user (all roles isolated by uploaded_by)."""
    if not _fotopia_tenant_id:
        raise HTTPException(status_code=503, detail="Service not ready")
    ctx = _build_context(authorization, None)
    conn = psycopg2.connect(config.DATABASE_URL)
    try:
        with conn.cursor() as cur:
            cur.execute("SET ROLE fotopia_app")
            cur.execute("SET app.current_tenant_id = %s", (ctx.tenant_id,))
            cur.execute(
                """
                SELECT id, filename, is_sensitive, sensitivity_scan,
                       uploaded_by, created_at
                FROM demo_documents
                WHERE tenant_id = %s AND uploaded_by = %s
                ORDER BY created_at DESC LIMIT 50
                """,
                (ctx.tenant_id, ctx.user_id),
            )
            cols = ["id", "filename", "is_sensitive", "sensitivity_scan", "uploaded_by", "created_at"]
            rows = []
            for row in cur.fetchall():
                r = dict(zip(cols, row))
                r["id"] = str(r["id"])
                r["created_at"] = r["created_at"].isoformat() if r["created_at"] else None
                rows.append(r)
        return {"documents": rows}
    finally:
        conn.close()


class CheckShareRequest(BaseModel):
    recipient_role: str | None = None
    recipient_employee_code: str | None = None
    recipient_name: str | None = None


@app.post("/api/documents/demo/{doc_id}/check-share")
def check_demo_document_share(
    doc_id: str,
    body: CheckShareRequest,
    authorization: str | None = Header(default=None),
):
    """Check whether sharing a demo document with recipient_role is appropriate."""
    if not _fotopia_tenant_id:
        raise HTTPException(status_code=503, detail="Service not ready")
    if not all(c in "0123456789abcdefABCDEF-" for c in doc_id):
        raise HTTPException(status_code=400, detail="Invalid document ID")
    ctx = _build_context(authorization, None)

    from workflow.appropriateness import check_share_mismatch

    conn = psycopg2.connect(config.DATABASE_URL)
    try:
        with conn.cursor() as cur:
            cur.execute("SET ROLE fotopia_app")
            cur.execute("SET app.current_tenant_id = %s", (ctx.tenant_id,))
            cur.execute(
                "SELECT content_text, filename FROM demo_documents WHERE id = %s::uuid AND tenant_id = %s::uuid",
                (doc_id, ctx.tenant_id),
            )
            row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Document not found")
        content_text, filename = row

        # Resolve recipient_role from employee_code if provided
        recipient_role = body.recipient_role
        recipient_name = body.recipient_name
        if body.recipient_employee_code:
            with conn.cursor() as cur:
                cur.execute("SET ROLE fotopia_app")
                cur.execute("SET app.current_tenant_id = %s", (ctx.tenant_id,))
                cur.execute(
                    """
                    SELECT u.role, e.full_name FROM users u
                    JOIN employees e ON e.id = u.employee_id AND e.tenant_id = u.tenant_id
                    WHERE u.tenant_id = %s::uuid AND e.employee_code = %s
                    LIMIT 1
                    """,
                    (ctx.tenant_id, body.recipient_employee_code),
                )
                emp_row = cur.fetchone()
            if emp_row:
                recipient_role = emp_row[0]
                recipient_name = recipient_name or emp_row[1]

        decision = check_share_mismatch(
            content=content_text,
            recipient_role=recipient_role,
            sharer_role=ctx.role,
            document_title=filename,
            llm_provider=_llm,
        )

        if not decision.flagged:
            return {"flagged": False, "message": "No restrictions — safe to share"}

        # Write workflow_events row so the human decision can be recorded later
        event_id = str(_uuid.uuid4())
        with conn.cursor() as cur:
            cur.execute("SET ROLE fotopia_app")
            cur.execute("SET app.current_tenant_id = %s", (ctx.tenant_id,))
            cur.execute(
                """
                INSERT INTO workflow_events
                    (id, tenant_id, event_type, actor_user_id, data)
                VALUES (%s::uuid, %s::uuid, 'appropriateness_flag', %s, %s)
                """,
                (
                    event_id, ctx.tenant_id, ctx.user_id,
                    json.dumps({
                        "flag_code": decision.flag_code,
                        "reason": decision.reason,
                        "severity": decision.severity,
                        "doc_id": doc_id,
                        "recipient_role": recipient_role,
                        "recipient_name": recipient_name,
                        "human_decision": None,
                    }),
                ),
            )
            cur.execute(
                """
                INSERT INTO audit_log (tenant_id, actor_user_id, actor_role, tool_name,
                    tool_input, outcome, authz_decision, result_summary, latency_ms, action)
                VALUES (%s, %s, %s, 'appropriateness_check', %s, 'success', 'allowed', %s, 0, 'data_read')
                """,
                (
                    ctx.tenant_id, ctx.user_id, ctx.role,
                    json.dumps({"doc_id": doc_id, "recipient_role": recipient_role, "recipient_name": recipient_name}),
                    f"Sensitivity flag: {decision.flag_code} — {decision.reason[:120]}",
                ),
            )
        conn.commit()
        return {
            "flagged": True,
            "flag_code": decision.flag_code,
            "severity": decision.severity,
            "reason": decision.reason,
            "event_id": event_id,
        }
    finally:
        conn.close()


@app.delete("/api/documents/demo/reset")
def reset_demo_documents(authorization: str | None = Header(default=None)):
    """Clear all demo documents for this tenant (hr_manager/admin only)."""
    if not _fotopia_tenant_id:
        raise HTTPException(status_code=503, detail="Service not ready")
    ctx = _build_context(authorization, None)
    if ctx.role not in ("hr_manager", "admin"):
        raise HTTPException(status_code=403, detail="hr_manager or admin role required")

    conn = psycopg2.connect(config.DATABASE_URL)
    try:
        with conn.cursor() as cur:
            cur.execute("SET ROLE fotopia_app")
            cur.execute("SET app.current_tenant_id = %s", (ctx.tenant_id,))
            cur.execute(
                "DELETE FROM demo_documents WHERE tenant_id = %s RETURNING id",
                (ctx.tenant_id,),
            )
            deleted_count = cur.rowcount
            cur.execute(
                """
                DELETE FROM workflow_events
                WHERE tenant_id = %s AND event_type = 'appropriateness_flag'
                """,
                (ctx.tenant_id,),
            )
        conn.commit()
        return {"deleted_count": deleted_count, "message": "Demo reset complete"}
    finally:
        conn.close()


@app.get("/api/documents/recent")
def get_recent_documents(authorization: str | None = Header(default=None)):
    """Return recently generated system documents from audit_log."""
    if not _fotopia_tenant_id:
        raise HTTPException(status_code=503, detail="Service not ready")
    ctx = _build_context(authorization, None)

    doc_tools = (
        "generate_salary_certificate",
        "generate_twimc_letter",
        "generate_experience_certificate",
    )
    conn = psycopg2.connect(config.DATABASE_URL)
    try:
        with conn.cursor() as cur:
            cur.execute("SET app.current_tenant_id = %s", (ctx.tenant_id,))
            if ctx.role == "employee":
                cur.execute(
                    """
                    SELECT tool_name, tool_input, result_summary, actor_role, created_at
                    FROM audit_log
                    WHERE tenant_id = %s
                      AND tool_name = ANY(%s)
                      AND outcome = 'success'
                      AND tool_input->>'employee_code' = %s
                    ORDER BY created_at DESC LIMIT 20
                    """,
                    (ctx.tenant_id, list(doc_tools), ctx.employee_code),
                )
            else:
                cur.execute(
                    """
                    SELECT tool_name, tool_input, result_summary, actor_role, created_at
                    FROM audit_log
                    WHERE tenant_id = %s
                      AND tool_name = ANY(%s)
                      AND outcome = 'success'
                    ORDER BY created_at DESC LIMIT 20
                    """,
                    (ctx.tenant_id, list(doc_tools)),
                )
            rows = []
            for tool_name, tool_input, result_summary, actor_role, created_at in cur.fetchall():
                doc_type = tool_name.replace("generate_", "")
                emp_code = (tool_input or {}).get("employee_code", "")
                rows.append({
                    "doc_type": doc_type,
                    "employee_code": emp_code,
                    "result_summary": result_summary,
                    "generated_by_role": actor_role,
                    "created_at": created_at.isoformat() if created_at else None,
                })
        return {"documents": rows}
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
