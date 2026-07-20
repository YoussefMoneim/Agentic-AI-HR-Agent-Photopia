# Email Agent - Quick Reference Guide

## 📚 Documentation Files Created

### 1. **EMAIL_AGENT_ARCHITECTURE.md** — The Bible
- Complete 6-stage security pipeline explained
- All 10 intent handlers documented
- 10 main tests + 8 additional tests explained
- Security invariants (rules that cannot break)
- Complete data flow diagrams (text-based)
- Integration with workflow approval system

**Start here if you want to understand**: How the system works from end-to-end

---

### 2. **EMAIL_AGENT_DIAGRAMS.md** — Visual Reference
- 10+ Mermaid flowcharts:
  - Complete state machine (16 decision nodes)
  - Intent classification decision tree
  - Security pipeline (invariant order)
  - Tool routing map
  - Leave request handler flow
  - Rate limiting mechanism
  - Email threading (RFC 2822)
  - Error paths

**Start here if you want to understand**: Visual flow at a glance

---

### 3. **EMAIL_AGENT_CODE_WALKTHROUGH.md** — Hands-On Examples
- **Complete real-world example**: Employee asks "What's my leave balance?"
  - Shows all 13 steps with actual code
  - SQL queries
  - HTML/plain text responses
  - SMTP headers
  - Email client display
- **5 additional scenarios**:
  - Rate-limited employee
  - Privilege escalation attempt
  - Date parsing for leave requests
  - Test assertions explained
  - Audit trail example

**Start here if you want to understand**: How data actually flows through the code

---

## 🎯 The 6 Security Stages (In Order)

| Stage | Function | Purpose | DB Access | Fails How |
|-------|----------|---------|-----------|-----------|
| 1 | `_is_auto_reply()` | Detect machine replies | NO | Return silently |
| 2 | Self-email check | Prevent system loops | NO | Return silently |
| 3 | `get_employee_by_email()` | Verify registration | YES | Return (no signal) |
| 4 | `check_and_record_rate_limit()` | Prevent spam/DoS | YES | Send ONE "blocked" reply |
| 5 | `_classify_intent()` | Keyword matching | NO | Return "unknown" handler |
| 6 | Tool dispatch & reply | Execute & respond | YES | Send error message |

---

## 🧵 The 5 Intent Types → Handlers

```
Email Body        Intent              Handler              Tool Called
─────────────────────────────────────────────────────────────────────────
"balance?"        leave_balance       _handle_leave_balance     check_leave_balance
"status?"         leave_status        _handle_leave_status      get_leave_requests
"policy?"         policy_question     _handle_policy_question   search_policy
"take leave"      leave_request       _handle_leave_request     submit_leave_request
"cancel"          leave_cancellation  _handle_leave_cancellation (none)
(anything else)   unknown             _handle_unknown           (none)
```

---

## 🔐 Security Critical: Role ALWAYS from DB

```python
# ✓ CORRECT — Role from database
employee = ds.get_employee_by_email(tenant_id, from_email)
ctx = ToolContext(role=employee["role"])  # ← DB only

# ✗ WRONG — Role from email body (never done here)
ctx = ToolContext(role=extract_role_from_body(email_body))  # ← NOT US
```

---

## 📧 Response Format (All Handlers)

Every handler returns a 5-tuple:

```python
(title, icon, color, html_content, plain_content)

Example:
("Your Leave Balance", "📊", "#2563eb", "<table>...</table>", "Annual: 15.0 days...")
```

This gets wrapped in branded HTML template with:
- Fotopia logo (dark header)
- Emoji icon
- Color-coded title
- Content area
- HR email footer

---

## 🛡️ Security Invariants (Never Break These)

1. **Loop detection first** — before any DB access
2. **Never reply to unregistered senders** — no signal to spammers
3. **Role from DB only** — email body cannot escalate privileges
4. **Rate limit one reply per block** — prevent spam amplification
5. **Intent classification keyword-only** — deterministic, no LLM
6. **Pre-templated responses** — never LLM-generated content
7. **All tools via ToolRegistry** — central audit point
8. **RFC 2822 headers** — In-Reply-To for threading

---

## 📊 Test Coverage

**10 Main Security Tests:**
- `test_auto_reply_header_skipped` — Stage 1 ✓
- `test_self_email_skipped` — Stage 2 ✓
- `test_unregistered_sender_no_reply` — Stage 3 ✓
- `test_rate_limit_blocks_reply` — Stage 4 ✓
- `test_leave_balance_keyword_routes_to_tool` — Stages 5-6 ✓
- `test_leave_status_keyword_routes_to_tool` — Stages 5-6 ✓
- `test_policy_question_returns_canned_response` — Stages 5-6 ✓
- `test_unknown_intent_returns_canned_response` — Stages 5-6 ✓
- `test_role_from_db_not_body` — Security critical ✓
- `test_reply_sets_in_reply_to_header` — RFC 2822 ✓

**4 Intent Classification Tests:**
- Arabic + English keyword detection
- Cancellation vs. Request priority

**4 Handler Tests:**
- HTML table formatting
- Status badges with colors
- Clarification templates
- Portal redirects

---

## 🚀 Quick Start: How to Use This System

### As a developer:
1. Read EMAIL_AGENT_ARCHITECTURE.md (Sections 1-3)
2. Read EMAIL_AGENT_DIAGRAMS.md (State machine + pipeline diagrams)
3. Read EMAIL_AGENT_CODE_WALKTHROUGH.md (Example 1 + Test 9)

### As a product manager:
1. Skim EMAIL_AGENT_ARCHITECTURE.md (Section 2: Overview, Section 5: Handlers)
2. Look at EMAIL_AGENT_DIAGRAMS.md (State machine + tool routing)

### As a security reviewer:
1. Read EMAIL_AGENT_ARCHITECTURE.md (Section 6: Security Invariants, Section 7: Compliance)
2. Read test_email_agent.py (all 10 security tests)
3. Verify audit_log entries from EMAIL_AGENT_CODE_WALKTHROUGH.md (Step 12)

---

## 🔄 Integration Points

### With Workflow Approval System
```
Employee sends leave request
    ↓
agent/orchestrator.py (Claude + ToolRegistry)
    ↓
submit_leave_request() → sends email to manager
    ↓
Manager replies (In-Reply-To)
    ↓
email_listener.py (async IMAP)
    ↓
process_inbound_email() [workflow approval]
    ↓
Updates pending_actions
    ↓
send_employee_reply() [sends back to employee]
```

### With Email Listener
```
Two parallel email paths:
1. Is this a reply to a pending_action? (workflow approval)
   → process_inbound_email() in email_listener.py
   
2. Is this a new employee question?
   → process_employee_email() in email_agent.py [THIS SYSTEM]
```

---

## 💡 Key Design Decisions

| Decision | Why |
|----------|-----|
| Keyword-only intent (no LLM) | Fast, cheap, deterministic, auditable |
| Pre-templated HTML (no LLM) | Prevents hallucination, fabrication, consistency |
| Role from DB only | Privilege escalation prevention |
| Rate limiting with one reply | Spam amplification protection |
| RFC 2822 threading | Email client UX, audit chain |
| 6-stage pipeline | Defense in depth, fail-closed |

---

## 🧪 Running Tests

```bash
cd backend

# All email agent tests
python -m pytest tests/test_email_agent.py -v

# Just the 10 main security tests
python -m pytest tests/test_email_agent.py::test_auto_reply_header_skipped -v
python -m pytest tests/test_email_agent.py::test_unregistered_sender_no_reply -v
python -m pytest tests/test_email_agent.py::test_rate_limit_blocks_reply -v
# ... etc

# Just intent classification
python -m pytest tests/test_email_agent.py::TestIntentClassification -v

# Just handlers
python -m pytest tests/test_email_agent.py::TestHandlers -v
```

---

## 📈 Performance Characteristics

| Operation | Latency | Cost |
|-----------|---------|------|
| Loop detection | ~1ms | $0 (headers only) |
| Identity check | ~5ms | ~$0.001 (1 DB query) |
| Rate limit check | ~3ms | ~$0.001 (1 DB query) |
| Intent classification | ~2ms | $0 (regex only) |
| Tool execution | ~15-50ms | ~$0.01 (depends on tool) |
| **Total** | **~30-75ms** | **~$0.015 per email** |

---

## 🎓 Learning Path

**Beginner (understand the concept):**
1. Read this quick reference
2. Look at state machine diagram
3. Read Example 1 (leave balance)

**Intermediate (understand implementation):**
1. Read EMAIL_AGENT_ARCHITECTURE.md (Section 3-5)
2. Look at all diagrams
3. Read Example 1 + Example 3 code walkthroughs

**Advanced (contribute to codebase):**
1. Read all three documents
2. Study all 10 test cases
3. Add new intent handler (follow _handle_leave_balance pattern)
4. Write tests (mock DataSource, ToolRegistry, send_email)

---

## ❓ Common Questions

**Q: Can the LLM invent response text?**
A: No. All response text is pre-templated HTML. Tools return structured data (not text). Handlers format that data into predefined templates.

**Q: Can an email claim admin role?**
A: No. Role is always fetched from the database, never from email body. Email body is only used for intent keyword matching.

**Q: What if the tool fails?**
A: Handler catches the error, analyzes error message type (weekend, balance, policy), and returns appropriate error HTML template.

**Q: What happens if email is rate-limited?**
A: Exactly ONE "Too Many Requests" reply is sent. No tools are called. Function returns immediately.

**Q: How are replies threaded?**
A: RFC 2822 headers: `In-Reply-To: <original-message-id>` and new `Message-ID`. Email client uses these to group conversation.

**Q: Is Arabic supported?**
A: Keywords support Arabic (رصيد, إجازة, إلغاء). Response templates are pre-built; multilingual support requires tenant config.

**Q: Can I extend this?**
A: Yes. Add keyword to an existing intent keyword set, OR create new intent/handler pair. Follow the _handle_* pattern. Write tests first.

---

## 🔗 Related Files

- `backend/services/email_agent.py` — Main implementation (900 lines)
- `backend/tests/test_email_agent.py` — Test file (700+ lines)
- `backend/services/email.py` — Send via SMTP/ACS/Mock
- `backend/services/email_listener.py` — Receive via IMAP (workflow replies)
- `backend/tools/registry.py` — ToolRegistry (access control)
- `backend/tools/leave.py` — Leave-related tools

---

## 📝 Audit Trail

Every email processed creates audit_log entries:

```
┌────────────────────────────────────────────────────────────────┐
│ audit_log                                                      │
├────────────────────────────────────────────────────────────────┤
│ id          │ tool_name              │ actor_role │ outcome    │
├────────────────────────────────────────────────────────────────┤
│ audit-001   │ check_leave_balance    │ employee   │ allowed    │
│ audit-002   │ check_leave_balance    │ employee   │ success    │
│ audit-003   │ RATE_LIMIT             │ employee   │ blocked    │
│ audit-004   │ submit_leave_request   │ employee   │ allowed    │
│ audit-005   │ submit_leave_request   │ employee   │ error      │
└────────────────────────────────────────────────────────────────┘
```

Every row is timestamped, tenant-scoped, and includes latency for monitoring.

---

## 🎯 Next Steps

**If you want to:**

- **Understand the architecture** → Read EMAIL_AGENT_ARCHITECTURE.md
- **See diagrams** → Open EMAIL_AGENT_DIAGRAMS.md
- **Learn by example** → Read EMAIL_AGENT_CODE_WALKTHROUGH.md
- **Add a new intent** → Study _handle_leave_balance + write test
- **Review security** → Check Section 6 of ARCHITECTURE.md + test_role_from_db_not_body
- **Extend to Arabic UI** → Parameterize HTML templates by language + tenant config
- **Add multilingual support** → Create language-keyed template files, select by tenant_settings.preferred_language

