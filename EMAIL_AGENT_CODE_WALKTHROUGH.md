# Email Agent - Code Walkthrough with Examples

## File Structure

```
backend/
├── services/
│   ├── email_agent.py          ← Main entry point: process_employee_email()
│   ├── email.py                ← send_email() wrapper (SMTP/ACS/Mock)
│   ├── email_listener.py       ← Inbound IMAP loop (workflow approvals)
│   └── # Note: email_agent.py processes NON-workflow emails
│
├── tools/
│   ├── registry.py             ← ToolRegistry with role-based access
│   ├── base.py                 ← ToolContext, ToolResult
│   ├── leave.py                ← check_leave_balance, submit_leave_request, etc.
│   └── policy.py               ← search_policy tool
│
└── tests/
    └── test_email_agent.py     ← 18 test cases (10 main + 4 intent + 4 handlers)
```

---

## Complete Example Walkthrough

### Example 1: Employee Asks for Leave Balance

#### Step 1: Email Arrives at IMAP Inbox

```
From: saif@fotopia.com
To: hr@fotopia.com (noreply@fotopia.com)
Subject: Leave Balance
Date: 2026-06-28 10:30:00 UTC
Message-ID: <original@client.mail.server>
Auto-Submitted: no
X-AutoReply: (not set)

Body:
Hi HR,

What is my remaining annual leave balance for 2026?

Thanks,
Saif Ahmed
```

#### Step 2: IMAP Listener Calls process_employee_email()

```python
from services.email_agent import process_employee_email

# Called by the email listener loop (runs async in background)
process_employee_email(
    ds=postgresql_datasource,              # Live Postgres DB
    tenant_id="fotopia-tenant-uuid",
    from_email="saif@fotopia.com",
    body_text="Hi HR,\n\nWhat is my remaining annual leave balance for 2026?...",
    in_reply_to_message_id="<original@client.mail.server>",
    our_message_id="<noreply@fotopia.com>",
    msg_headers={
        "subject": "Leave Balance",
        "from": "saif@fotopia.com",
        "auto-submitted": "no",
        "date": "2026-06-28 10:30:00 UTC",
    },
)
```

#### Step 3: Security Pipeline Executes

**Stage 1: Loop Detection**
```python
def _is_auto_reply(msg_headers: dict) -> bool:
    for raw_header, value in msg_headers.items():
        h = raw_header.lower()           # → "auto-submitted"
        v = (value or "").strip().lower() # → "no"
        if h == "auto-submitted" and v not in ("", "no"):
            return True  # ← Would return True if auto-submitted=auto-replied
    return False  # ← Returns False (not an auto-reply)

# In process_employee_email():
if _is_auto_reply(msg_headers):  # False
    return  # ← Doesn't execute
```

**Stage 2: Self-Email Check**
```python
own_address = config.IMAP_USERNAME.strip().lower()  # "noreply@fotopia.com"
if own_address and from_email.strip().lower() == own_address:
    # from_email = "saif@fotopia.com"
    # own_address = "noreply@fotopia.com"
    # These don't match
    return  # ← Doesn't execute
```

**Stage 3: Identity Check**
```python
employee = ds.get_employee_by_email(tenant_id, from_email)
# DB Query (simplified):
# SELECT employee_code, full_name, email, role, department
# FROM employees
# WHERE tenant_id = 'fotopia-tenant-uuid' AND email = 'saif@fotopia.com'
#
# Returns:
# {
#   "id": "employee-uuid-001",
#   "employee_code": "EMP001",
#   "full_name": "Saif Ahmed",
#   "email": "saif@fotopia.com",
#   "notification_email": None,
#   "department": "R&D",
#   "position": "Software Engineer",
#   "role": "employee",
# }

if not employee:  # Found it
    return  # ← Doesn't execute (employee exists)

display_name = employee.get("full_name", from_email)  # "Saif Ahmed"
subject = msg_headers.get("subject", "") or "HR Enquiry"  # "Leave Balance"
```

**Stage 4: Rate Limit Check**
```python
rl = ds.check_and_record_rate_limit(tenant_id, from_email)
# DB Query (simplified):
# SELECT COUNT(*) as count, MAX(created_at) as latest
# FROM rate_limits
# WHERE tenant_id = 'fotopia-tenant-uuid'
#   AND sender_email = 'saif@fotopia.com'
#   AND created_at > NOW() - INTERVAL 1 HOUR
#
# Assume count = 1 (first email this hour)
# Increment count to 2
#
# Returns:
# {
#   "allowed": True,
#   "count": 2,
#   "blocked_until": None,
# }

if not rl["allowed"]:  # allowed = True
    # Rate limited path (doesn't execute)
    return

# Continues with tool execution
```

**Stage 5: Intent Classification**
```python
intent = _classify_intent(body_text)

def _classify_intent(body_text: str) -> str:
    snippet = body_text[:500].lower()
    # snippet = "hi hr,\n\nwhat is my remaining annual leave balance for 2026?..."
    
    # Check in order (cancellation → policy → request → balance → status → unknown)
    if any(kw in snippet for kw in _LEAVE_CANCELLATION_KEYWORDS):
        # "cancel" in snippet? NO
        pass
    
    if any(kw in snippet for kw in _POLICY_KEYWORDS):
        # "policy", "rules", etc. in snippet? NO
        pass
    
    if any(kw in snippet for kw in _LEAVE_REQUEST_KEYWORDS):
        # "take leave", "request", etc. in snippet? NO
        pass
    
    if any(kw in snippet for kw in _BALANCE_KEYWORDS):
        # _BALANCE_KEYWORDS = frozenset([
        #   "balance", "remaining", "how many days", "days left",
        #   "entitlement", "leave balance", "رصيد", "أيام متبقية",
        # ])
        # "remaining" in snippet? YES ✓ MATCH
        return "leave_balance"  # ← Returns "leave_balance"
    
    if any(kw in snippet for kw in _STATUS_KEYWORDS):
        pass
    
    return "unknown"

intent = "leave_balance"
_log.info("email_agent: from=%s intent=%s", "saif@fotopia.com", "leave_balance")
```

#### Step 6: Build Security Context

```python
def _build_context(employee: dict, tenant_id: str) -> ToolContext:
    return ToolContext(
        tenant_id="fotopia-tenant-uuid",
        user_id="EMP001",                           # ← employee_code
        role="employee",                            # ← FROM DB, not email
        employee_code="EMP001",
        display_name="Saif Ahmed",
    )

ctx = _build_context(employee, "fotopia-tenant-uuid")
```

#### Step 7: Get Tool Registry

```python
def _get_registry(ds: "DataSource") -> "ToolRegistry":
    global _registry
    if _registry is None:
        from audit.logger import AuditLogger
        from tools.registry import build_registry
        
        audit_logger = AuditLogger(config.DATABASE_URL)
        _registry = build_registry(ds, audit_logger)
        # build_registry() instantiates all tools:
        # [
        #   CheckLeaveBalance(),
        #   SubmitLeaveRequest(),
        #   GetLeaveRequests(),
        #   SearchPolicy(),
        #   GenerateSalaryCertificate(),
        #   ... (10 tools total)
        # ]
    return _registry

registry = _get_registry(ds)
```

#### Step 8: Dispatch to Handler

```python
# In process_employee_email():
if intent == "leave_balance":
    title, icon, color, html, plain = _handle_leave_balance(ctx, registry, display_name)
    # → Calls _handle_leave_balance(ctx, registry, "Saif Ahmed")
```

#### Step 9: Handler Executes Tool

```python
def _handle_leave_balance(
    ctx: ToolContext,
    registry: "ToolRegistry",
    name: str  # "Saif Ahmed"
) -> tuple[str, str, str, str, str]:
    
    # Call the tool via ToolRegistry (central audit point)
    result = registry.execute("check_leave_balance", {}, ctx)
    # ToolRegistry.execute() does:
    #   1. Check if tool exists → YES
    #   2. Check if role "employee" is in allowed_roles → YES
    #   3. Tool executes:
    #      - Row-level check: can employee see their own data? YES
    #      - DB query: SELECT balances FROM leaves WHERE employee_code = 'EMP001'
    #      - Computes balance_days = allocated - used - pending
    #      - Returns ToolResult(success=True, data={...})
    #   4. Log to audit_log

    if result.success and result.data:
        balances = result.data.get("balances") or []
        # balances = [
        #   {
        #     "name_en": "Annual Leave",
        #     "balance_days": 15.0,
        #     "allocated_days": 21.0,
        #     "used_days": 6.0,
        #     "pending_days": 0.0,
        #   },
        #   {
        #     "name_en": "Sick Leave",
        #     "balance_days": 9.0,
        #     "allocated_days": 10.0,
        #     "used_days": 1.0,
        #     "pending_days": 0.0,
        #   },
        # ]
        
        balances = [b for b in balances if float(b.get("allocated_days") or 0) > 0]
        # Filter out zero-allocated types
        
        if balances:
            # Build HTML table
            rows = ""
            plain_lines = []
            
            for i, b in enumerate(balances):
                lt_name = "Annual Leave"  # or "Sick Leave"
                remaining = 15.0  # or 9.0
                allocated = 21.0  # or 10.0
                used = 6.0  # or 1.0
                bg = "#f8f8fb" if i % 2 == 0 else "#ffffff"  # Alternating row colors
                
                rows += (
                    f"<tr style='background:{bg}'>"
                    f"<td style='padding:10px 16px;color:#666;font-size:14px;"
                    f"border-bottom:1px solid #e0e0e0'>{lt_name}</td>"
                    f"<td style='padding:10px 16px;color:#1a1a2e;font-weight:600;"
                    f"font-size:14px;border-bottom:1px solid #e0e0e0'>{remaining:.1f} days</td>"
                    f"<td style='padding:10px 16px;color:#888;font-size:13px;"
                    f"border-bottom:1px solid #e0e0e0'>of {allocated:.0f} allocated "
                    f"({used:.1f} used)</td></tr>"
                )
                # rows now contains both leave types
                
                plain_lines.append(
                    f"  {lt_name}: {remaining:.1f} days remaining "
                    f"(of {allocated:.0f} allocated)"
                )
            
            html = (
                f"<p style='color:#444;font-size:14px;margin:0 0 16px 0'>"
                f"Dear Saif Ahmed,<br><br>"
                f"Here is your current leave balance:</p>"
                f"<table width='100%' cellpadding='0' cellspacing='0' "
                f"style='border:1px solid #e0e0e0;border-radius:6px;overflow:hidden'>"
                f"<tr style='background:#f0f4f8'>"
                f"<td style='padding:10px 16px;font-weight:bold;color:#1a1a2e;font-size:13px'>Leave Type</td>"
                f"<td style='padding:10px 16px;font-weight:bold;color:#1a1a2e;font-size:13px'>Remaining</td>"
                f"<td style='padding:10px 16px;font-weight:bold;color:#1a1a2e;font-size:13px'>Details</td>"
                f"</tr>"
                f"{rows}"
                f"</table>"
                f"<p style='color:#888;font-size:12px;margin-top:16px'>"
                f"To submit a leave request, reply with your leave type and dates, "
                f"or visit the HR portal.</p>"
            )
            
            plain = (
                f"Dear Saif Ahmed,\n\n"
                f"Your current leave balance:\n"
                f"  Annual Leave: 15.0 days remaining (of 21.0 allocated)\n"
                f"  Sick Leave: 9.0 days remaining (of 10.0 allocated)"
            )
            
            return (
                "Your Leave Balance",  # title
                "📊",                   # icon
                "#2563eb",              # color (blue)
                html,                   # html_content
                plain,                  # plain_content
            )
```

#### Step 10: Send Branded Reply

```python
def _send_reply(
    to_email="saif@fotopia.com",
    subject="Leave Balance",
    title="Your Leave Balance",
    icon="📊",
    color="#2563eb",
    html_content="<p>Dear Saif Ahmed,...</p><table>...",
    plain_content="Dear Saif Ahmed,\n\nYour current leave balance:...",
    in_reply_to="<original@client.mail.server>",
    our_message_id="<noreply@fotopia.com>",
) -> None:
    
    # Generate RFC 2822 Message-ID for threading
    domain = config.SMTP_FROM_ADDRESS.split("@")[-1]  # "fotopiatech.com"
    new_message_id = f"<fotopia-hr-agent-a1b2c3d4@{domain}>"
    # → "<fotopia-hr-agent-a1b2c3d4@fotopiatech.com>"
    
    # Add "Re: " prefix
    reply_subject = (
        subject if subject.lower().startswith("re:") else f"Re: {subject}"
    )
    # → "Re: Leave Balance"
    
    # Build branded HTML email
    body_html = f"""<!DOCTYPE html>
<html lang="en">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="margin:0;padding:0;background:#f4f4f7;font-family:Arial,Helvetica,sans-serif">
<table width="100%" cellpadding="0" cellspacing="0">
<tr><td align="center" style="padding:30px 15px">
<table width="600" cellpadding="0" cellspacing="0" style="max-width:600px;width:100%">
  <tr>
    <td style="background:#0a0c1a;padding:24px 30px;text-align:center;border-radius:8px 8px 0 0">
      <div style="color:#fff;font-size:20px;font-weight:bold;letter-spacing:1px">Fotopia HR System</div>
      <div style="color:#c9a84c;font-size:12px;margin-top:5px">WIN Holding Group &mdash; HR Portal</div>
    </td>
  </tr>
  <tr>
    <td style="background:#fff;padding:32px 36px;border-radius:0 0 8px 8px">
      <div style="font-size:38px;text-align:center;margin-bottom:14px">📊</div>
      <h2 style="margin:0 0 20px 0;color:#2563eb;font-size:20px;text-align:center">Your Leave Balance</h2>
      <p style="color:#444;font-size:14px;margin:0 0 16px 0">
      Dear Saif Ahmed,<br><br>
      Here is your current leave balance:
      </p>
      <table width='100%' cellpadding='0' cellspacing='0' 
      style='border:1px solid #e0e0e0;border-radius:6px;overflow:hidden'>
      <tr style='background:#f0f4f8'>
      <td style='padding:10px 16px;font-weight:bold;color:#1a1a2e;font-size:13px'>Leave Type</td>
      <td style='padding:10px 16px;font-weight:bold;color:#1a1a2e;font-size:13px'>Remaining</td>
      <td style='padding:10px 16px;font-weight:bold;color:#1a1a2e;font-size:13px'>Details</td>
      </tr>
      <tr style='background:#f8f8fb'>
      <td style='padding:10px 16px;color:#666;font-size:14px;border-bottom:1px solid #e0e0e0'>Annual Leave</td>
      <td style='padding:10px 16px;color:#1a1a2e;font-weight:600;font-size:14px;border-bottom:1px solid #e0e0e0'>15.0 days</td>
      <td style='padding:10px 16px;color:#888;font-size:13px;border-bottom:1px solid #e0e0e0'>of 21.0 allocated (6.0 used)</td>
      </tr>
      <tr style='background:#ffffff'>
      <td style='padding:10px 16px;color:#666;font-size:14px;border-bottom:1px solid #e0e0e0'>Sick Leave</td>
      <td style='padding:10px 16px;color:#1a1a2e;font-weight:600;font-size:14px;border-bottom:1px solid #e0e0e0'>9.0 days</td>
      <td style='padding:10px 16px;color:#888;font-size:13px;border-bottom:1px solid #e0e0e0'>of 10.0 allocated (1.0 used)</td>
      </tr>
      </table>
      <p style='color:#888;font-size:12px;margin-top:16px'>
      To submit a leave request, reply with your leave type and dates, or visit the HR portal.
      </p>
      <hr style="border:none;border-top:1px solid #e0e0e0;margin:24px 0">
      <p style="margin:0;font-size:11px;color:#aaa;text-align:center">
        Fotopia HR System &mdash; Automated reply. For assistance contact
        <a href="mailto:hr@fotopia.com" style="color:#c9a84c">hr@fotopia.com</a>
      </p>
    </td>
  </tr>
</table>
</td></tr>
</table>
</body>
</html>"""
    
    send_email(
        to_email="saif@fotopia.com",
        subject="Re: Leave Balance",
        body_html=body_html,
        body_plain="Dear Saif Ahmed,\n\nYour current leave balance:\n  Annual Leave: 15.0 days remaining...",
        message_id="<fotopia-hr-agent-a1b2c3d4@fotopiatech.com>",
        in_reply_to="<original@client.mail.server>",
    )
```

#### Step 11: SMTP Sends Email

```python
# In services/email.py:
def send_email(
    to_email: str,
    subject: str,
    body_html: str,
    body_plain: str,
    message_id: str | None = None,
    in_reply_to: str | None = None,
) -> bool:
    
    # Try SMTP (since SMTP_HOST is configured)
    return _send_via_smtp(
        to_email="saif@fotopia.com",
        subject="Re: Leave Balance",
        body_html=body_html,
        body_plain=body_plain,
        message_id="<fotopia-hr-agent-a1b2c3d4@fotopiatech.com>",
        in_reply_to="<original@client.mail.server>",
    )

def _send_via_smtp(
    to_email: str, subject: str, body_html: str, body_plain: str,
    message_id: str | None,
) -> bool:
    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = "Re: Leave Balance"
        msg["From"] = "hr@fotopia.com"  # config.SMTP_FROM_ADDRESS
        msg["To"] = "saif@fotopia.com"
        msg["Message-ID"] = "<fotopia-hr-agent-a1b2c3d4@fotopiatech.com>"
        msg["In-Reply-To"] = "<original@client.mail.server>"
        
        # Add parts (plain first, HTML second)
        msg.attach(MIMEText(body_plain, "plain"))
        msg.attach(MIMEText(body_html, "html"))
        
        # Send via SMTP
        server = smtplib.SMTP(config.SMTP_HOST, config.SMTP_PORT)
        server.starttls()
        server.login(config.SMTP_USERNAME, config.SMTP_PASSWORD)
        server.send_message(msg)
        server.quit()
        
        _log.info(
            "EMAIL [SMTP] TO=%s | SUBJECT=%s | MESSAGE-ID=%s",
            to_email, subject, message_id,
        )
        return True
    except Exception:
        _log.exception("SMTP send failed for %s", to_email)
        return False
```

#### Step 12: Audit Logging

```python
# ToolRegistry.execute() logs:
self._audit.log(
    ctx,                                  # ToolContext (tenant_id, user_id, role)
    "check_leave_balance",                # tool_name
    {},                                   # tool_input
    result,                               # ToolResult(success, data, error)
    "allowed",                            # authz_decision
    23,                                   # latency_ms
)

# audit_log row inserted:
# INSERT INTO audit_log (
#   tenant_id, actor_id, actor_role, tool_name, tool_input,
#   result_summary, authz_decision, latency_ms, created_at
# ) VALUES (
#   'fotopia-tenant-uuid',
#   'EMP001',
#   'employee',
#   'check_leave_balance',
#   '{}',
#   'Balance queried successfully',
#   'allowed',
#   23,
#   NOW()
# );
```

#### Step 13: Employee Receives Email

```
From: hr@fotopia.com
To: saif@fotopia.com
Subject: Re: Leave Balance
Date: 2026-06-28 10:30:15 UTC
Message-ID: <fotopia-hr-agent-a1b2c3d4@fotopiatech.com>
In-Reply-To: <original@client.mail.server>
Content-Type: multipart/alternative; boundary="..."

[HTML BODY]:
┌─────────────────────────────────────────────────────┐
│ Fotopia HR System                                   │
│ WIN Holding Group — HR Portal                       │
├─────────────────────────────────────────────────────┤
│                                                     │
│   📊 Your Leave Balance                             │
│                                                     │
│   Dear Saif Ahmed,                                  │
│                                                     │
│   Here is your current leave balance:              │
│   ┌─────────────────────────────────────┐          │
│   │ Leave Type  │ Remaining │ Details    │          │
│   ├─────────────────────────────────────┤          │
│   │ Annual      │ 15.0 days │ of 21      │          │
│   │ Sick        │ 9.0 days  │ of 10      │          │
│   └─────────────────────────────────────┘          │
│                                                     │
│   For assistance: hr@fotopia.com                   │
│                                                     │
└─────────────────────────────────────────────────────┘

Reply-Token: <fotopia-hr-agent-a1b2c3d4@fotopiatech.com>
```

#### Email Client Display

```
🔙 CONVERSATION THREAD:

┌─────────────────────────────────────────┐
│ HR Enquiry                              │
│ From: Saif Ahmed to HR                  │
│ 10:30 AM                                │
├─────────────────────────────────────────┤
│ Hi HR,                                  │
│                                         │
│ What is my remaining annual leave       │
│ balance for 2026?                       │
│                                         │
│ Thanks,                                 │
│ Saif Ahmed                              │
└─────────────────────────────────────────┘

┌─────────────────────────────────────────┐
│ 📊 RE: Leave Balance                    │
│ From: Fotopia HR System                 │
│ 10:30 AM (< 1 second later)             │
├─────────────────────────────────────────┤
│ Dear Saif Ahmed,                        │
│                                         │
│ Here is your current leave balance:     │
│                                         │
│ Leave Type   Remaining  Details         │
│ Annual       15.0 days  of 21 allocated │
│ Sick         9.0 days   of 10 allocated │
│                                         │
│ To submit a leave request, reply with   │
│ your leave type and dates, or visit     │
│ the HR portal.                          │
│                                         │
│ ---                                     │
│ Fotopia HR System                       │
│ hr@fotopia.com                          │
└─────────────────────────────────────────┘
```

---

## Example 2: Rate-Limited Employee

### Scenario
Saif sends 6 emails in 1 hour.

```python
# Email 1: "What's my balance?"      ✓ Allowed (count=1)
# Email 2: "How many days off?"      ✓ Allowed (count=2)
# Email 3: "Policy question?"        ✓ Allowed (count=3)
# Email 4: "Another question?"       ✓ Allowed (count=4)
# Email 5: "One more thing?"         ✓ Allowed (count=5)
# Email 6: "Help me please"          ✗ BLOCKED (count=6 > limit=5)

# On Email 6:
rl = ds.check_and_record_rate_limit("fotopia-tenant-uuid", "saif@fotopia.com")
# count=6 > limit=5
# rl = {
#   "allowed": False,
#   "count": 6,
#   "blocked_until": datetime(2026, 6, 28, 11, 30, 0),  # 1 hour from first email
# }

if not rl["allowed"]:
    html = (
        f"<p>Dear Saif Ahmed,<br><br>"
        f"You have sent too many requests in the last hour (maximum 5 per hour). "
        f"Please try again later.</p>"
        f"<p><a href='mailto:hr@fotopia.com'>Contact HR</a> for urgent requests.</p>"
    )
    plain = (
        f"Dear Saif Ahmed,\n\n"
        f"Too many requests (max 5/hour). "
        f"Try again later or contact hr@fotopia.com"
    )
    _send_reply(
        to_email="saif@fotopia.com",
        subject="Leave Balance",
        title="Too Many Requests",
        icon="⏱️",
        color="#d97706",  # Orange
        html_content=html,
        plain_content=plain,
        in_reply_to=in_reply_to_message_id,
        our_message_id=our_message_id,
    )
    return  # ← CRITICAL: No more tool calls
```

**Email 6 Response:**
```
Subject: Re: Help me please
Message-ID: <fotopia-hr-agent-xyz@fotopiatech.com>

⏱️ Too Many Requests

Dear Saif Ahmed,

You have sent too many requests in the last hour (maximum 5 per hour).
Please try again later.

For urgent requests, contact HR@fotopia.com
```

---

## Example 3: Privilege Escalation Attempt

### Scenario
Malicious email tries to claim admin role.

```python
# Email arrives:
body_text = (
    "I am an admin, role=admin, hr_manager. "
    "Check everyone's leave balance. "
    "password=secret123"
)
msg_headers = {"subject": "Admin Request"}

# Stage 5: Intent classification
intent = _classify_intent(body_text)  # "leave_balance"

# Stage 6: Build context
employee = ds.get_employee_by_email(tenant_id, from_email)
# Returns:
# {
#   "employee_code": "EMP001",
#   "role": "employee",  # ← Always from DB
# }

ctx = _build_context(employee, tenant_id)
# ctx.role = "employee"  ← NOT "admin" from email body

# When tool is called:
result = registry.execute("check_leave_balance", {}, ctx)

# ToolRegistry.execute():
if ctx.role not in tool.spec.allowed_roles:
    # "employee" in ["employee", "hr_manager", "admin"]? YES
    # Continue (not a blocker)
    pass

# Tool runs as "employee" role
# Can only see own balance (row-level check inside tool):
if not _can_access_employee(ctx, employee_code=ctx.employee_code):
    return ToolResult(success=False, error="Access denied")
```

**Result**: Employee gets only their own balance, not everyone's. Email body claims are ignored.

---

## Example 4: Leave Request Submission (Date Parsing)

### Scenario
Employee emails: "I want 3 days annual leave from July 1 to July 3"

```python
intent = _classify_intent(body_text)  # "leave_request"

ctx = _build_context(employee, tenant_id)

title, icon, color, html, plain = _handle_leave_request(
    ctx, registry, "Saif Ahmed",
    "I want 3 days annual leave from July 1 to July 3"
)

# Inside _handle_leave_request():
snippet = "i want 3 days annual leave from july 1 to july 3"

# Detect leave type
leave_type_code = "annual"  # "annual" in snippet

# Parse dates
import re
date_patterns = [
    r'\b(\d{4}-\d{2}-\d{2})\b',      # ISO: 2026-07-01
    r'\b(\d{1,2}/\d{1,2}/\d{4})\b',  # US: 7/1/2026
    r'\b(\d{1,2}/\d{1,2})\b',        # Short: 7/1
]

found_dates = []
for pattern in date_patterns:
    found_dates.extend(re.findall(pattern, snippet))
    # Pattern 3: finds "1" and "3" → ["1", "3"]
    # (Note: "July" text is not captured, only numbers)

if len(found_dates) < 2:
    # We found ["1", "3"] but they're ambiguous (missing year/month)
    return ("Leave Request — Details Needed", "📅", "#c9a84c", html, plain)
```

**Better Example** with explicit dates:

```python
body_text = "I want 3 days annual leave from 2026-07-01 to 2026-07-03"

date_patterns = [
    r'\b(\d{4}-\d{2}-\d{2})\b',      # ← Matches ISO format
    r'\b(\d{1,2}/\d{1,2}/\d{4})\b',
    r'\b(\d{1,2}/\d{1,2})\b',
]

found_dates = re.findall(date_patterns[0], body_text)
# found_dates = ["2026-07-01", "2026-07-03"]
# len(found_dates) == 2 ✓

start_date = "2026-07-01"
end_date = "2026-07-03"

tool_result = registry.execute("submit_leave_request", {
    "leave_type_code": "annual",
    "start_date": "2026-07-01",
    "end_date": "2026-07-03",
    "reason": "Submitted via email",
}, ctx)

# Tool runs, checks:
# 1. Are dates in the future? YES
# 2. Are they working days? Need to check calendar
# 3. Does employee have balance? 15.0 >= 3? YES
# 4. Does it violate policy? NO
# → Return ToolResult(success=True, data={request_id: "LR-2026-001"})

if tool_result.success:
    html = (
        f"<p>Your leave request has been submitted successfully.</p>"
        f"<table>"
        f"<tr><td>Leave Type</td><td>Annual Leave</td></tr>"
        f"<tr><td>Dates</td><td>2026-07-01 → 2026-07-03</td></tr>"
        f"<tr><td>Status</td><td>Pending Approval</td></tr>"
        f"<tr><td>Sent to</td><td>Ahmed Hassan</td></tr>"
        f"<tr><td>Reference</td><td>LR-2026-0...</td></tr>"
        f"</table>"
        f"<p>You will receive an email when a decision is made.</p>"
    )
    return ("Leave Request Submitted", "✅", "#16a34a", html, plain)
```

---

## Test Assertions Explained

### Test 1: Auto-Reply Loop Detection

```python
def test_auto_reply_header_skipped():
    ds = _make_ds()  # Mock DataSource
    
    _call_agent(
        ds,
        msg_headers={"auto-submitted": "auto-replied", "subject": "Out of Office"},
    )
    
    # ASSERTION: ds.get_employee_by_email was NOT called
    ds.get_employee_by_email.assert_not_called()  # ← Zero DB access
```

**Why this matters:**
- Loop detection must execute BEFORE any database work
- If an auto-reply email header is present, we skip it immediately
- No database hit = no resource waste on machine-generated mail

---

### Test 5: Intent Routing to Tool

```python
def test_leave_balance_keyword_routes_to_tool():
    emp = _registered_employee()
    ds = _make_ds(employee=emp)
    
    mock_registry = MagicMock()
    mock_registry.execute.return_value = ToolResult(
        success=True,
        data={"employee_name": "Saif Ahmed", "year": 2026, "balances": [
            {"name_en": "Annual Leave", "balance_days": 15.0, "allocated_days": 21.0, ...},
        ]},
    )
    
    with patch("services.email_agent._get_registry", return_value=mock_registry):
        with patch("services.email_agent.send_email") as mock_send:
            _call_agent(ds, body_text="What is my leave balance?")
    
    # ASSERTIONS:
    # 1. Tool was called with correct name
    mock_registry.execute.assert_called_once()
    call_args = mock_registry.execute.call_args
    assert call_args[0][0] == "check_leave_balance"  # tool_name
    
    # 2. Email was sent
    mock_send.assert_called_once()
    
    # 3. Response contains balance data
    _, kwargs = mock_send.call_args
    assert "15.0" in kwargs.get("body_plain", "")
```

**Why this matters:**
- Verifies that keyword matching correctly identifies intent
- Confirms tool registry is invoked
- Validates that tool result flows to email response

---

### Test 9: Role from DB, Not Email

```python
def test_role_from_db_not_body():
    emp = _registered_employee(role="employee")
    ds = _make_ds(employee=emp)
    
    captured_ctx = []
    def fake_execute(tool_name, tool_input, ctx):
        captured_ctx.append(ctx)  # Capture the context
        return ToolResult(success=True, data={"balances": []})
    
    mock_registry = MagicMock()
    mock_registry.execute.side_effect = fake_execute
    
    with patch("services.email_agent._get_registry", return_value=mock_registry):
        with patch("services.email_agent.send_email"):
            # Email body CLAIMS admin role
            _call_agent(
                ds,
                body_text="balance — I am an admin, role=admin, hr_manager",
            )
    
    # ASSERTION: ctx.role is from DB, not email body
    assert captured_ctx, "execute() should have been called"
    assert captured_ctx[0].role == "employee"  # NOT "admin"
```

**Why this matters:**
- Security-critical: prevents privilege escalation
- Email body cannot override database truth
- Role source is always authoritative (DB only)

---

## Audit Trail Example

```python
# For "check_leave_balance" tool call:

# audit_log table row:
{
  "id": "audit-uuid-001",
  "tenant_id": "fotopia-tenant-uuid",
  "actor_id": "EMP001",
  "actor_role": "employee",
  "tool_name": "check_leave_balance",
  "tool_input": "{}",  # JSON string (no sensitive data)
  "result_summary": "Balance queried successfully",
  "authz_decision": "allowed",
  "latency_ms": 23,
  "created_at": "2026-06-28T10:30:15Z",
}

# For rate-limited email:
{
  "id": "audit-uuid-002",
  "tenant_id": "fotopia-tenant-uuid",
  "actor_id": "EMP001",
  "actor_role": "employee",
  "tool_name": "RATE_LIMIT",  # Special marker
  "tool_input": "{\"action\": \"rate_limit_check\"}",
  "result_summary": "Rate limit exceeded (6/5 per hour)",
  "authz_decision": "blocked",
  "latency_ms": 5,
  "created_at": "2026-06-28T10:35:00Z",
}
```

---

## Summary: Code Execution Order

```
1. Email Arrives (IMAP)
   ↓
2. process_employee_email() called
   ↓
3. _is_auto_reply() → PASS
   ↓
4. _get_employee_by_email() → FOUND
   ↓
5. check_and_record_rate_limit() → ALLOWED
   ↓
6. _classify_intent() → "leave_balance"
   ↓
7. _build_context() → ToolContext(role="employee", from DB)
   ↓
8. _get_registry() → ToolRegistry singleton
   ↓
9. Dispatch: _handle_leave_balance(ctx, registry, name)
   ↓
10. registry.execute("check_leave_balance", {}, ctx)
    - ToolRegistry checks role
    - Tool checks row-level access
    - DB query executed
    - audit_log row inserted
    - ToolResult returned
   ↓
11. Handler builds HTML from tool result
   ↓
12. _send_reply() with branded HTML
   ↓
13. send_email() via SMTP/ACS/Mock
   ↓
14. Email lands in inbox
   ↓
15. Employee reads response in < 1 second
```

