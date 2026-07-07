# Email Agent Architecture & Complete Flow Explanation

## 📋 Overview

The email agent system (`services/email_agent.py` + `tests/test_email_agent.py`) is a **secure, keyword-driven email dispatcher** that processes employee emails and sends back branded HTML responses. It does NOT use an LLM for content generation—instead, it uses a **strict 6-stage security pipeline** to classify intent, route to tools, and send pre-formatted responses.

### Key Philosophy
- **Policy before prompt**: Controls are enforced BEFORE tools run
- **Fail-closed on ambiguity**: Any unclear request returns generic help text, never auto-executes
- **No LLM content generation**: All response text is pre-templated (HTML/plain text)
- **Audit every decision**: Rate limits, access checks, and tool calls are logged

---

## 🔐 The 6-Stage Security Pipeline

Every inbound email passes through these stages in strict order. **Order is INVARIANT** — never reorder these.

### Stage 1: Loop Detection (Header Check, ZERO DB Access)
**Purpose**: Prevent infinite reply loops early, before any database work.

```python
def _is_auto_reply(msg_headers: dict) -> bool:
    """Check for machine-generated reply signals"""
```

**What it checks:**
- `Auto-Submitted: auto-replied` — automatic vacation/out-of-office replies
- `X-AutoReply`, `X-AutoRespond`, `Precedence: bulk/list/junk` — bounce headers
- Any header signaling this is NOT a human message

**Why first:**
- No database cost if it's a loop
- Prevents cascading auto-replies (email loops)
- Stateless security: headers alone tell the story

**Test**: `test_auto_reply_header_skipped()` — auto-reply headers cause immediate return, zero DB calls

---

### Stage 2: Identity Check (DB Lookup)
**Purpose**: Verify the sender is a registered employee before going further.

```python
employee = ds.get_employee_by_email(tenant_id, from_email)
if not employee:
    return  # NEVER send_email() to unregistered senders
```

**What it does:**
- Queries the `employees` table: does this email match an employee record?
- Extracts: `employee_code`, `full_name`, `role`, `department`
- If not found → **silent exit** (no reply sent)

**Why this matters:**
- Only registered employees can trigger tool execution
- External emails are silently ignored (no signal to spammers)
- Prevents spam amplification

**Test**: `test_unregistered_sender_no_reply()` — stranger@external.com gets no response

---

### Stage 3: Rate Limiting (DB Upsert + Check)
**Purpose**: Prevent DoS attacks and email spam from the same sender.

```python
rl = ds.check_and_record_rate_limit(tenant_id, from_email)
if not rl["allowed"]:
    # ONE polite reply sent, no tools called
    _send_reply(..., title="Too Many Requests", ...)
    return
```

**What it does:**
- Increments a counter for this `tenant_id + from_email` in DB
- Checks if they've exceeded the limit (e.g., 5 emails/hour)
- Returns: `{"allowed": bool, "count": int, "blocked_until": datetime}`

**Behavior when rate-limited:**
- Send exactly ONE reply: "Too many requests. Try again later."
- **Block further tool calls** (exit immediately)
- Prevents spam campaigns from flooding the system

**Test**: `test_rate_limit_blocks_reply()` — rate limit triggers one reply, no tool execution

---

### Stage 4: Intent Classification (Keyword Match, NO LLM)
**Purpose**: Determine what the employee is asking for, using only regex + keyword sets.

```python
def _classify_intent(body_text: str) -> str:
    snippet = body_text[:_MAX_BODY_CHARS].lower()  # First 500 chars only
    
    # Cancellation checked FIRST (more specific than request)
    if any(kw in snippet for kw in _LEAVE_CANCELLATION_KEYWORDS):
        return "leave_cancellation"
    
    # Policy checked before request (more specific)
    if any(kw in snippet for kw in _POLICY_KEYWORDS):
        return "policy_question"
    
    # Now check leave_request, balance, status
    if any(kw in snippet for kw in _LEAVE_REQUEST_KEYWORDS):
        return "leave_request"
    
    if any(kw in snippet for kw in _BALANCE_KEYWORDS):
        return "leave_balance"
    
    if any(kw in snippet for kw in _STATUS_KEYWORDS):
        return "leave_status"
    
    return "unknown"
```

**Intent types:**
| Intent | Keywords | Example | Tool Called |
|--------|----------|---------|-------------|
| `leave_balance` | "balance", "remaining", "days left", "رصيد" | "What's my leave balance?" | `check_leave_balance` |
| `leave_status` | "status", "pending", "approved", "طلب" | "Status of my request?" | `get_leave_requests` |
| `policy_question` | "policy", "rules", "eligible", "سياسة" | "How many sick days?" | `search_policy` |
| `leave_request` | "take leave", "request", "apply", "إجازة" | "3 days off from July 1" | `submit_leave_request` |
| `leave_cancellation` | "cancel", "withdraw", "إلغاء" | "Cancel my leave request" | None (template only) |
| `unknown` | None matched | "zxqwerty🦆" | None (help text) |

**Why keyword matching (not LLM)?**
- Fast (milliseconds, no API calls)
- Deterministic (same input = same output)
- Auditable (no black-box "thinking")
- Doesn't require Claude API (zero cost)

**Test**: `TestIntentClassification` — multiple test cases for keyword detection, including Arabic

---

### Stage 5: Tool Dispatch (Using Real DB Role)
**Purpose**: Execute the appropriate tool using the employee's actual database role.

```python
ctx = _build_context(employee, tenant_id)
registry = _get_registry(ds)

if intent == "leave_balance":
    result = registry.execute("check_leave_balance", {}, ctx)
```

**Critical detail:**
- `ctx.role = employee["role"]` — **sourced from the DB, not from email body**
- Email body cannot claim "I am admin" and escalate privileges
- `ToolRegistry.execute()` re-checks role before running tool

```python
def _build_context(employee: dict, tenant_id: str) -> ToolContext:
    """Role ALWAYS sourced from DB join, never from email content"""
    return ToolContext(
        tenant_id=tenant_id,
        user_id=employee["employee_code"],
        role=employee.get("role", "employee"),  # ← DB only
        employee_code=employee["employee_code"],
        display_name=employee.get("full_name", ""),
    )
```

**Test**: `test_role_from_db_not_body()` — email body claims "admin" but ctx.role stays "employee"

---

### Stage 6: Branded HTML Reply (Pre-Templated, Never LLM)
**Purpose**: Send a professional HTML response with data from the tool result.

```python
def _send_reply(
    to_email: str,
    subject: str,
    title: str,          # "Your Leave Balance"
    icon: str,           # "📊"
    color: str,          # "#2563eb"
    html_content: str,   # Pre-built table
    plain_content: str,  # Plain text fallback
    in_reply_to: str | None,
    our_message_id: str | None,
) -> None:
    # Build RFC 2822 Message-ID so replies thread correctly
    new_message_id = f"<fotopia-hr-agent-{uuid.uuid4()}@{domain}>"
    
    # Send branded HTML response
    send_email(
        to_email=to_email,
        subject=reply_subject,
        body_html=body_html,          # Pre-built HTML template
        body_plain=plain_content,
        message_id=new_message_id,
        in_reply_to=in_reply_to or our_message_id,
    )
```

**Response format:**
```
Subject: Re: [Original Subject]

[Branded HTML email with:]
  - Fotopia logo/header
  - Icon emoji (📊, 📋, 📖, etc.)
  - Color-coded title
  - Data table (leave balance, status, policy, etc.)
  - Footer with HR contact email
  - Reply-Token for correlation

[Plain text fallback for email clients that don't support HTML]
```

**Test**: `test_reply_sets_in_reply_to_header()` — reply includes correct In-Reply-To header for threading

---

## 🔄 Complete Email Flow Example

### Scenario: Employee asks "What's my leave balance?"

**Step 1: Email arrives**
```
From: saif@fotopia.com
Subject: Leave Balance
Body: What is my remaining leave balance?
```

**Step 2: Loop detection**
- Headers: no `Auto-Submitted`, no `X-AutoReply` → PASS
- Continue

**Step 3: Identity check**
- Query: `SELECT * FROM employees WHERE email = 'saif@fotopia.com' AND tenant_id = 'tenant-uuid'`
- Result: `{ employee_code: "EMP001", full_name: "Saif Ahmed", role: "employee", ... }`
- Continue

**Step 4: Rate limit check**
- Increment: `rate_limits['saif@fotopia.com'] += 1`
- Check: count=1 < limit=5 → PASS
- Continue

**Step 5: Intent classification**
```python
snippet = "what is my remaining leave balance?"
if "balance" in snippet:  # ✓ matches _BALANCE_KEYWORDS
    return "leave_balance"
```

**Step 6: Tool dispatch**
```python
ctx = ToolContext(
    tenant_id="tenant-uuid",
    user_id="EMP001",
    role="employee",  # ← DB only, not claimed in email
    employee_code="EMP001",
    display_name="Saif Ahmed",
)

result = registry.execute("check_leave_balance", {}, ctx)
# Returns:
# {
#   "employee_name": "Saif Ahmed",
#   "year": 2026,
#   "balances": [
#     {"name_en": "Annual Leave", "balance_days": 15.0, "allocated_days": 21.0, ...},
#     {"name_en": "Sick Leave", "balance_days": 9.0, "allocated_days": 10.0, ...}
#   ]
# }
```

**Step 7: Handler builds HTML response**
```python
def _handle_leave_balance(ctx, registry, name):
    # Extract balances from result
    rows = """
    <tr style='background:#f8f8fb'>
      <td style='padding:10px 16px'>Annual Leave</td>
      <td style='padding:10px 16px;font-weight:600'>15.0 days</td>
      <td>of 21.0 allocated (6.0 used)</td>
    </tr>
    <tr>
      <td>Sick Leave</td>
      <td style='font-weight:600'>9.0 days</td>
      <td>of 10.0 allocated (1.0 used)</td>
    </tr>
    """
    
    html = f"""
    <p>Dear Saif Ahmed,</p>
    <p>Here is your current leave balance:</p>
    <table>{rows}</table>
    """
    
    plain = """
    Dear Saif Ahmed,
    
    Your current leave balance:
      Annual Leave: 15.0 days remaining (of 21.0 allocated)
      Sick Leave: 9.0 days remaining (of 10.0 allocated)
    """
    
    return ("Your Leave Balance", "📊", "#2563eb", html, plain)
```

**Step 8: Send branded reply**
```
Subject: Re: Leave Balance
Message-ID: <fotopia-hr-agent-a1b2c3d4-e5f6@fotopiatech.com>
In-Reply-To: [original message ID]

[HTML email with Fotopia branding]

📊 Your Leave Balance
┌──────────────────────────────────────────────┐
│ Annual Leave: 15.0 days (of 21.0 allocated)  │
│ Sick Leave: 9.0 days (of 10.0 allocated)     │
└──────────────────────────────────────────────┘

Reply-Token: <fotopia-hr-agent-a1b2c3d4-e5f6@fotopiatech.com>
```

**Result**: Employee receives professional HTML response in < 1 second, no LLM cost

---

## 🛠️ The 10 Test Cases (Explained)

### Test Group 1: Security Pipeline Invariants (Tests 1-4)

#### Test 1: `test_auto_reply_header_skipped()`
- **Setup**: Email with `auto-submitted: auto-replied` header
- **Expected**: No DB calls (`ds.get_employee_by_email` not called)
- **Why**: Loop detection catches it before identity check
- **Security principle**: Fail-closed on machine-generated mail

#### Test 2: `test_self_email_skipped()`
- **Setup**: Email from our own IMAP address (hr@fotopia.com)
- **Expected**: No DB calls
- **Why**: Prevents the system replying to itself
- **Security principle**: Out-of-band channel isolation

#### Test 3: `test_unregistered_sender_no_reply()`
- **Setup**: Email from external user (stranger@external.com)
- **Expected**: No `send_email()` call (no signal to spammers)
- **Why**: Only registered employees can use the system
- **Security principle**: Information disclosure prevention

#### Test 4: `test_rate_limit_blocks_reply()`
- **Setup**: Employee with `allowed=False` (rate limit exceeded)
- **Expected**: Exactly ONE "Too Many Requests" reply, no tool calls
- **Why**: Prevent spam/DoS from authenticated users
- **Security principle**: Resource exhaustion protection

---

### Test Group 2: Intent Classification & Tool Dispatch (Tests 5-8)

#### Test 5: `test_leave_balance_keyword_routes_to_tool()`
- **Setup**: Email body = "What is my leave balance?"
- **Expected**:
  - Intent classified as `leave_balance`
  - `registry.execute("check_leave_balance", ...)` called
  - Reply contains "15.0 days"
- **Why**: Validates keyword matching + tool routing
- **Captures**: Intent classification works; tool execution happens; response builds correctly

#### Test 6: `test_leave_status_keyword_routes_to_tool()`
- **Setup**: Email body = "What is the status of my request?"
- **Expected**:
  - Intent classified as `leave_status`
  - `registry.execute("get_leave_requests", ...)` called
  - Reply contains leave request status table
- **Why**: Different intent leads to different tool

#### Test 7: `test_policy_question_returns_canned_response()`
- **Setup**: Email body = "What is the HR policy for sick leave?"
- **Expected**:
  - Intent classified as `policy_question`
  - `registry.execute("search_policy", ...)` called
  - Reply contains policy excerpt
- **Why**: Validates policy lookup via RAG/knowledge layer

#### Test 8: `test_unknown_intent_returns_canned_response()`
- **Setup**: Email body = "zxqwerty123 nothing here makes sense 🦆"
- **Expected**:
  - Intent classified as `unknown`
  - No tool called
  - Reply contains help text showing capabilities
- **Why**: Fail-closed on ambiguity; show user what we CAN do

---

### Test Group 3: Security & Compliance (Tests 9-10)

#### Test 9: `test_role_from_db_not_body()`
- **Setup**: Email claims "I am an admin, role=admin"
- **Expected**: `ctx.role = "employee"` (from DB, not email)
- **Why**: Prevents privilege escalation via email
- **Security principle**: Authentication source must be authoritative (DB only)

#### Test 10: `test_reply_sets_in_reply_to_header()`
- **Setup**: Inbound Message-ID = `<abc123@mail.example.com>`
- **Expected**: Reply sets `In-Reply-To: <abc123@mail.example.com>`
- **Why**: Ensures email threads correctly in client
- **Security principle**: Proper RFC 2822 compliance for audit trail

---

## 📝 Intent Handler Functions

### `_handle_leave_balance(ctx, registry, name) → (title, icon, color, html, plain)`
**Returns**: 5-tuple ready for `_send_reply()`

**Process**:
1. Call `registry.execute("check_leave_balance", {}, ctx)`
2. If success: build HTML table with balance data
3. If failure: return generic "Unable to retrieve" message

**Key output**:
- HTML table with leave types, days remaining, used, allocated
- Plain text fallback for old email clients

---

### `_handle_leave_status(ctx, registry, name) → tuple`
**Returns**: 5-tuple of (title, icon, color, html, plain)

**Process**:
1. Call `registry.execute("get_leave_requests", {"limit": 5}, ctx)`
2. Build HTML table with colour-coded status badges:
   - `#d97706` (orange) = pending_approval
   - `#16a34a` (green) = approved/completed
   - `#dc2626` (red) = rejected
   - `#6b7280` (gray) = cancelled

**Key feature**: Colour coding allows users to scan status at a glance

---

### `_handle_policy_question(ctx, registry, name, body_text) → tuple`
**Returns**: 5-tuple

**Process**:
1. Extract first 200 chars of email as query
2. Call `registry.execute("search_policy", {"query": query}, ctx)`
3. If results: show top result with source citation
4. If no results: generic "Contact HR" message

**Key principle**: Never LLM-generate policy — quote actual policy chunks

---

### `_handle_leave_request(ctx, registry, name, body_text) → tuple`
**Returns**: 5-tuple

**Process**:
1. Parse dates from email body using regex:
   - ISO format: `2026-07-21`
   - Slash format: `7/21/2026`
   - US format: `7/21`
2. Infer leave type from keywords: "sick" → sick, "hajj" → hajj, etc.
3. If dates missing: return "Details Needed" template (ask for dates)
4. If dates found: call `registry.execute("submit_leave_request", {...}, ctx)`
5. If success: confirm submission, show status=pending_approval
6. If failure: explain why (weekend, insufficient balance, policy constraint)

**Key limitation**: Cannot submit requests with policy exceptions. Those must go through portal.

---

### `_handle_leave_cancellation(name) → tuple`
**Returns**: 5-tuple

**Process**: NO tool called. Returns template that redirects to HR portal.

**Why**: Cancellations are complex (restore balance, notify manager). Portal handles this.

---

### `_handle_unknown(name) → tuple`
**Returns**: 5-tuple

**Process**: Return help text listing all supported intents with examples

**Example**:
```
I can help with the following:

1. Leave balance — "What is my annual leave balance?"
2. Submit leave — "I want 3 days annual leave from 2026-07-21"
3. Leave status — "What is the status of my leave request?"
4. Policy questions — "How many days of sick leave do I get?"

For other requests, contact hr@fotopia.com
```

---

## 📊 Data Flow Diagram

```
┌─────────────────────────────────────────────────────────────────────────────┐
│ 1. Email Arrives                                                            │
│    From: saif@fotopia.com                                                   │
│    Body: "What is my leave balance?"                                        │
│    Headers: {subject: ..., auto-submitted: ?, X-AutoReply: ?, ...}         │
└────────────────────────┬────────────────────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ 2. Loop Detection                                                           │
│    Check _is_auto_reply(msg_headers)                                        │
│    → If True: RETURN (skip, no reply)                                       │
│    → If False: Continue                                                     │
└────────────────────────┬────────────────────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ 3. Self-Email Check                                                         │
│    If from_email == config.IMAP_USERNAME: RETURN (skip)                    │
│    Else: Continue                                                           │
└────────────────────────┬────────────────────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ 4. Identity Check                                                           │
│    DB: SELECT FROM employees WHERE email = 'saif@fotopia.com'              │
│    → If NOT found: RETURN (no reply to unregistered)                        │
│    → If found: Continue with employee data                                  │
└────────────────────────┬────────────────────────────────────────────────────┘
                         │
                         ▼ (employee = {code: EMP001, role: employee, ...})
┌─────────────────────────────────────────────────────────────────────────────┐
│ 5. Rate Limit Check                                                         │
│    DB: SELECT count FROM rate_limits WHERE sender = 'saif@fotopia.com'     │
│    → If blocked: send_reply(title="Too Many Requests") + RETURN            │
│    → If allowed: Continue                                                   │
└────────────────────────┬────────────────────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ 6. Intent Classification                                                    │
│    snippet = body_text[:500].lower()                                        │
│    Keyword match: "balance" → leave_balance                                 │
│    intent = "leave_balance"                                                 │
└────────────────────────┬────────────────────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ 7. Build Security Context                                                   │
│    ctx = ToolContext(                                                       │
│      tenant_id="tenant-uuid",                                               │
│      user_id="EMP001",                                                      │
│      role="employee",  ← FROM DB, NOT FROM EMAIL                           │
│      employee_code="EMP001",                                                │
│      display_name="Saif Ahmed"                                              │
│    )                                                                        │
└────────────────────────┬────────────────────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ 8. Dispatch to Handler                                                      │
│    if intent == "leave_balance":                                            │
│        _handle_leave_balance(ctx, registry, display_name)                   │
│                                                                             │
│    Handler calls: registry.execute("check_leave_balance", {}, ctx)         │
│    ToolRegistry applies:                                                    │
│      - Role check: is "employee" allowed to call "check_leave_balance"?    │
│      - Row-level check: can employee see their own data?                    │
│      - Execute tool                                                        │
│      - Log to audit_log                                                     │
└────────────────────────┬────────────────────────────────────────────────────┘
                         │
                         ▼ (result.data = {balances: [{Annual: 15.0, ...}]})
┌─────────────────────────────────────────────────────────────────────────────┐
│ 9. Build Branded HTML Response                                              │
│    title = "Your Leave Balance"                                             │
│    icon = "📊"                                                              │
│    color = "#2563eb"                                                        │
│    html = <table>...</table>  (pre-formatted, never LLM-generated)         │
│    plain = "Annual Leave: 15.0 days..."                                    │
│                                                                             │
│    Return (title, icon, color, html, plain)                                │
└────────────────────────┬────────────────────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ 10. Send Reply via _send_reply()                                            │
│     - Generate RFC 2822 Message-ID                                          │
│     - Wrap HTML in branded template (logo, footer, HR contact)             │
│     - Set In-Reply-To header for threading                                 │
│     - Call send_email() (SMTP/ACS/Mock)                                     │
│     - Log to audit_log                                                      │
└─────────────────────────────────────────────────────────────────────────────┘
                         │
                         ▼
                    EMAIL SENT ✓
```

---

## 🔒 Security Invariants (MUST NOT Break)

| Invariant | Why | Test |
|-----------|-----|------|
| Auto-reply checked BEFORE identity | Prevent loops even for invalid senders | test_auto_reply_header_skipped |
| `send_email()` never called for unregistered senders | No signal to spammers | test_unregistered_sender_no_reply |
| Role sourced from DB, not email body | Prevent privilege escalation | test_role_from_db_not_body |
| Rate limit enforces exactly ONE reply per block | Prevent spam amplification | test_rate_limit_blocks_reply |
| Intent classification is keyword-only (no LLM) | Deterministic, auditable | TestIntentClassification |
| All response text is pre-templated (not LLM-generated) | Prevents fabrication, hallucination | All handler tests |
| Registry.execute() called for ALL tool access | Central audit point | test_leave_balance_keyword_routes_to_tool |
| In-Reply-To header set for threading | RFC 2822 compliance | test_reply_sets_in_reply_to_header |

---

## 🎯 Summary: Why This Architecture Works

1. **Zero LLM for content** → Fast, cheap, deterministic, auditable
2. **Keyword-only classification** → Can't be tricked by clever wording
3. **Strict security pipeline** → Fails closed; no shortcuts
4. **Role from DB only** → Email cannot escalate privileges
5. **Pre-templated responses** → Consistent, branded, professional
6. **Rate limiting** → Spam/DoS protection
7. **RFC 2822 compliance** → Emails thread correctly, chain of custody preserved

---

## 📚 How This Integrates with the Full HR Agent

```
Employee sends email
         ↓
    email_listener.py (async IMAP loop)
    OR
    /simulate-inbound endpoint (for testing)
         ↓
    Is this a workflow reply (In-Reply-To a pending_action)?
         ├─ YES → process_inbound_email() [workflow approval flow]
         │         Updates pending_action status (approved/rejected)
         │         → send_employee_reply() notifies employee
         │
         └─ NO → process_employee_email() [this agent]
                 Intent classification
                 → Calls tools (check_leave_balance, etc.)
                 → Sends branded HTML reply
```

---

## 🧪 Running Tests

```bash
cd backend
python -m pytest tests/test_email_agent.py -v

# Output:
# test_auto_reply_header_skipped PASSED
# test_self_email_skipped PASSED
# test_unregistered_sender_no_reply PASSED
# test_rate_limit_blocks_reply PASSED
# test_leave_balance_keyword_routes_to_tool PASSED
# test_leave_status_keyword_routes_to_tool PASSED
# test_policy_question_returns_canned_response PASSED
# test_unknown_intent_returns_canned_response PASSED
# test_role_from_db_not_body PASSED
# test_reply_sets_in_reply_to_header PASSED
# TestIntentClassification::test_leave_request_detected PASSED
# TestIntentClassification::test_leave_cancellation_detected_before_request PASSED
# ... (18 tests total)
```

---

## 🚀 Extensions (Not Yet Implemented)

- **Arabic email support**: Already coded in keyword sets (`"إجازة"`, `"رصيد"`, etc.)
- **Multilingual responses**: HTML/plain templates can be translated per tenant
- **Tool result caching**: Reduce DB hits for repeated queries
- **Manager replies**: Already infrastructure-ready (workflow approval path)
- **Document uploads**: Could extend to parse attachments (carefully, as untrusted data)

