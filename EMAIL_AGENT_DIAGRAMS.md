# Email Agent Flow Diagrams

## Complete Email Processing State Machine

```mermaid
stateDiagram-v2
    [*] --> LoopDetection
    
    LoopDetection --> CheckAutoReply{Is auto-reply\nheader?}
    CheckAutoReply -->|YES| Discard1["Discard<br/>(no DB calls)"]
    CheckAutoReply -->|NO| SelfEmailCheck
    
    SelfEmailCheck --> CheckSelf{Email from\nsystem address?}
    CheckSelf -->|YES| Discard2["Discard<br/>(prevent loops)"]
    CheckSelf -->|NO| IdentityCheck
    
    IdentityCheck --> QueryDB["DB: SELECT employee\nWHERE email = sender"]
    QueryDB --> EmployeeFound{Employee\nfound?}
    EmployeeFound -->|NO| Discard3["Discard<br/>(no signal to\nspammers)"]
    EmployeeFound -->|YES| RateLimit
    
    RateLimit --> CheckRL["DB: check_and_record_rate_limit"]
    CheckRL --> RLExceeded{Rate limit\nexceeded?}
    RLExceeded -->|YES| SendRLReply["Send ONE reply:<br/>Too Many Requests"]
    SendRLReply --> [*]
    RLExceeded -->|NO| IntentClass
    
    IntentClass --> ExtractSnippet["snippet = body[:500]"]
    ExtractSnippet --> ClassifyKeywords["Match keywords:<br/>cancel, policy,<br/>request, balance,<br/>status"]
    ClassifyKeywords --> IntentResult{Intent\ndetected?}
    
    IntentResult -->|leave_cancellation| Handler1["_handle_leave_cancellation"]
    IntentResult -->|policy_question| Handler2["_handle_policy_question<br/>→ search_policy tool"]
    IntentResult -->|leave_request| Handler3["_handle_leave_request<br/>→ submit_leave_request tool"]
    IntentResult -->|leave_balance| Handler4["_handle_leave_balance<br/>→ check_leave_balance tool"]
    IntentResult -->|leave_status| Handler5["_handle_leave_status<br/>→ get_leave_requests tool"]
    IntentResult -->|unknown| Handler6["_handle_unknown<br/>→ capabilities list"]
    
    Handler1 --> BuildContext["Build ToolContext<br/>role = employee.role<br/>(from DB only)"]
    Handler2 --> BuildContext
    Handler3 --> BuildContext
    Handler4 --> BuildContext
    Handler5 --> BuildContext
    Handler6 --> BuildContext
    
    BuildContext --> ExecuteTool["registry.execute(tool_name, args, ctx)"]
    ExecuteTool --> ToolResult["Tool returns:<br/>success: bool<br/>data: dict"]
    ToolResult --> BuildHTML["Build branded HTML<br/>response"]
    
    BuildHTML --> FormatResponse["Format (title, icon,<br/>color, html, plain)"]
    FormatResponse --> SendReply["_send_reply():<br/>- Generate Message-ID<br/>- Set In-Reply-To<br/>- Wrap in template<br/>- Call send_email()"]
    SendReply --> Audit["Log to audit_log:<br/>tool_name, actor_role,<br/>result, latency"]
    Audit --> [*]
    
    Discard1 --> [*]
    Discard2 --> [*]
    Discard3 --> [*]
```

---

## Intent Classification Decision Tree

```mermaid
graph TD
    A["Email Body<br/>(first 500 chars)"] --> B["Convert to lowercase<br/>extract keywords"]
    
    B --> C{Any cancellation<br/>keyword?<br/>cancel, withdraw,<br/>إلغاء}
    C -->|YES| C1["Intent = leave_cancellation"]
    C -->|NO| D
    
    D --> E{Any policy<br/>keyword?<br/>policy, rules,<br/>eligible, سياسة}
    E -->|YES| E1["Intent = policy_question"]
    E -->|NO| F
    
    F --> G{Any request<br/>keyword?<br/>take leave, apply,<br/>إجازة}
    G -->|YES| G1["Intent = leave_request"]
    G -->|NO| H
    
    H --> I{Any balance<br/>keyword?<br/>balance, remaining,<br/>رصيد}
    I -->|YES| I1["Intent = leave_balance"]
    I -->|NO| J
    
    J --> K{Any status<br/>keyword?<br/>status, pending,<br/>approved, طلب}
    K -->|YES| K1["Intent = leave_status"]
    K -->|NO| L
    
    L --> L1["Intent = unknown"]
    
    C1 --> M["Return handler result"]
    E1 --> M
    G1 --> M
    I1 --> M
    K1 --> M
    L1 --> M
```

---

## Security Pipeline (Order is INVARIANT)

```mermaid
graph LR
    A["Email Arrives"] --> B["Stage 1:<br/>Loop Detection<br/>(Header only<br/>NO DB)"]
    B -->|Pass| C["Stage 2:<br/>Identity Check<br/>(DB lookup)"]
    B -->|Fail| Z1["🛑 DISCARD<br/>No reply sent"]
    
    C -->|Found| D["Stage 3:<br/>Rate Limit<br/>(DB check)"]
    C -->|Not Found| Z2["🛑 DISCARD<br/>No reply to<br/>unregistered"]
    
    D -->|Allowed| E["Stage 4:<br/>Intent Classify<br/>(Keyword match)"]
    D -->|Blocked| Z3["⚠️ ONE Reply:<br/>Too Many<br/>Requests"]
    
    E --> F["Stage 5:<br/>Tool Dispatch<br/>(role from DB)"]
    
    F --> G["Stage 6:<br/>Branded HTML<br/>Reply<br/>(pre-templated)"]
    
    G --> H["✅ Email sent<br/>audit logged"]
    
    Z1 --> END["END"]
    Z2 --> END
    Z3 --> END
    H --> END
    
    style A fill:#e1f5ff
    style Z1 fill:#ffebee
    style Z2 fill:#ffebee
    style Z3 fill:#fff3e0
    style H fill:#e8f5e9
```

---

## Tool Routing by Intent

```mermaid
graph TD
    A["Intent Classified"] --> B{Which Intent?}
    
    B -->|leave_balance| B1["_handle_leave_balance"]
    B1 --> B1a["registry.execute<br/>check_leave_balance"]
    B1a --> B1b["Build table:<br/>Leave Type | Remaining | Allocated"]
    B1b --> R1["Return 5-tuple:<br/>title, icon, color,<br/>html, plain"]
    
    B -->|leave_status| B2["_handle_leave_status"]
    B2 --> B2a["registry.execute<br/>get_leave_requests"]
    B2a --> B2b["Build table with<br/>color-coded status"]
    B2b --> R1
    
    B -->|policy_question| B3["_handle_policy_question"]
    B3 --> B3a["registry.execute<br/>search_policy"]
    B3a --> B3b["Show top result<br/>with citation"]
    B3b --> R1
    
    B -->|leave_request| B4["_handle_leave_request"]
    B4 --> B4a["Parse dates from body"]
    B4a --> B4c{Dates<br/>found?}
    B4c -->|NO| B4d["Return clarification<br/>template"]
    B4c -->|YES| B4e["registry.execute<br/>submit_leave_request"]
    B4e --> B4f{Success?}
    B4f -->|YES| B4g["Show confirmation<br/>with request ID"]
    B4f -->|NO| B4h["Show error reason:<br/>weekend/balance/policy"]
    B4d --> R1
    B4g --> R1
    B4h --> R1
    
    B -->|leave_cancellation| B5["_handle_leave_cancellation"]
    B5 --> B5a["Return portal redirect<br/>No tool calls"]
    B5a --> R1
    
    B -->|unknown| B6["_handle_unknown"]
    B6 --> B6a["Return capabilities list"]
    B6a --> R1
    
    R1 --> R2["_send_reply<br/>Generate branded HTML"]
    R2 --> R3["send_email via<br/>SMTP/ACS/Mock"]
    R3 --> END["✅ Complete"]
    
    style R3 fill:#e8f5e9
    style END fill:#c8e6c9
```

---

## Leave Request Handler - Detailed Flow

```mermaid
graph TD
    A["Email: 'I want 3 days<br/>annual from 2026-07-21'"] --> B["Extract first 500 chars"]
    B --> C["Parse leave type<br/>sick? casual?<br/>hajj? → default annual"]
    C --> D["Regex search for dates:<br/>YYYY-MM-DD<br/>M/D/YYYY<br/>M/D"]
    D --> E{Found 2+<br/>dates?}
    
    E -->|NO| E1["Return template:<br/>Details Needed<br/>Ask for:<br/>- Type<br/>- Start date<br/>- End date<br/>- Reason"]
    
    E -->|YES| F["Extract start, end dates"]
    F --> G["Call registry.execute<br/>submit_leave_request"]
    G --> H{Success?}
    
    H -->|YES| H1["Extract request_id<br/>manager_name from result"]
    H1 --> H2["Build confirmation HTML:<br/>- Type: Annual Leave<br/>- Dates: 2026-07-21 → 2026-07-23<br/>- Status: Pending Approval<br/>- Sent to: [Manager Name]"]
    H2 --> H3["Return (title, icon,<br/>color, html, plain)"]
    
    H -->|NO| H4["Extract error message"]
    H4 --> H5{Error type?}
    H5 -->|weekend/weekend_day| H5a["Explanation:<br/>Dates fall on weekend"]
    H5 -->|balance/insufficient| H5b["Explanation:<br/>Insufficient balance"]
    H5 -->|threshold/cap/policy| H5c["Explanation:<br/>Policy constraint"]
    H5 -->|other| H5d["Explanation: [error]"]
    
    H5a --> H6["Build error HTML:<br/>Red banner with explanation"]
    H5b --> H6
    H5c --> H6
    H5d --> H6
    H6 --> H7["Return (title, icon,<br/>color, html, plain)"]
    
    E1 --> END["📋 Send reply"]
    H3 --> END
    H7 --> END
    
    style E1 fill:#fff3e0
    style H3 fill:#c8e6c9
    style H7 fill:#ffebee
```

---

## Security Context Building

```mermaid
graph TD
    A["Employee record from DB"] --> B["Extract:<br/>employee_code<br/>full_name<br/>role<br/>department"]
    
    B --> C["🔒 CRITICAL:<br/>Role ALWAYS from DB"]
    C --> D{Check:<br/>Is role in DB<br/>NOT from email?}
    D -->|✓ YES| E["✅ Safe"]
    D -->|✗ NO| F["🛑 SECURITY ERROR<br/>Email tried to claim role"]
    
    E --> G["Build ToolContext:"]
    G --> G1["tenant_id: from request"]
    G --> G2["user_id: employee_code"]
    G --> G3["role: employee.role ← DB"]
    G --> G4["employee_code: employee_code"]
    G --> G5["display_name: employee.full_name"]
    
    G1 --> H["Pass to ToolRegistry"]
    G2 --> H
    G3 --> H
    G4 --> H
    G5 --> H
    
    H --> I["ToolRegistry.execute()<br/>verifies role again"]
    I --> J["Tool executes with<br/>readonly context"]
    
    F --> K["🛑 DENY<br/>Log security event<br/>No tool execution"]
    
    style C fill:#fff3e0
    style E fill:#c8e6c9
    style F fill:#ffebee
    style J fill:#e8f5e9
```

---

## Email Threading (RFC 2822)

```mermaid
graph TD
    A["Inbound Email:"] --> A1["Message-ID: &lt;original@client.com&gt;<br/>From: saif@fotopia.com<br/>Subject: Leave Balance<br/>Body: What is my balance?"]
    
    A1 --> B["Agent processes<br/>intent = leave_balance"]
    
    B --> C["Agent generates reply:"]
    C --> C1["Generate NEW Message-ID:<br/>&lt;fotopia-hr-agent-UUID@fotopiatech.com&gt;"]
    C --> C2["Set In-Reply-To:<br/>&lt;original@client.com&gt;<br/>(from inbound Message-ID)"]
    C --> C3["Set Subject:<br/>Re: Leave Balance<br/>(adds 'Re: ' prefix)"]
    
    C1 --> D["send_email():<br/>SMTP sets headers"]
    C2 --> D
    C3 --> D
    
    D --> E["Email client receives:"]
    E --> E1["Message-ID: &lt;fotopia-hr-agent-UUID@...&gt;<br/>In-Reply-To: &lt;original@client.com&gt;<br/>Subject: Re: Leave Balance"]
    
    E1 --> F["Email client:<br/>Thread detection:<br/>This IS a reply to that message!"]
    
    F --> G["Display in conversation:<br/>┌─ Saif: 'What is my balance?'<br/>└─ Agent: 'Your balance is...'"]
    
    style C1 fill:#e1f5ff
    style C2 fill:#e1f5ff
    style C3 fill:#e1f5ff
    style G fill:#c8e6c9
```

---

## Rate Limiting Mechanism

```mermaid
graph TD
    A["Email arrives from<br/>saif@fotopia.com"] --> B["DB: check_and_record_rate_limit<br/>(tenant_id, sender_email)"]
    
    B --> C["SQL: SELECT count FROM<br/>rate_limits WHERE<br/>sender = saif@fotopia.com<br/>AND created_at > NOW() - 1 hour"]
    
    C --> D{Current<br/>count &lt; 5?}
    
    D -->|YES| D1["Increment count"]
    D1 --> D2["Return {allowed: true,<br/>count: 2,<br/>blocked_until: null}"]
    
    D -->|NO| D3["Return {allowed: false,<br/>count: 6,<br/>blocked_until:<br/>2026-06-30 15:00:00}"]
    
    D2 --> E["Process tool call"]
    D3 --> F["Send ONE reply:<br/>Too Many Requests<br/>blocked_until: ..."]
    
    E --> G["✅ Tool executed<br/>Response sent"]
    F --> H["⏱️ Rate limited<br/>No tool execution<br/>Return"]
    
    style D2 fill:#c8e6c9
    style D3 fill:#fff3e0
    style G fill:#e8f5e9
    style H fill:#ffebee
```

---

## HTML Response Template Structure

```
┌─────────────────────────────────────────────────────────┐
│ HEADER (Branded)                                        │
│ ┌─────────────────────────────────────────────────────┐ │
│ │ Fotopia HR System                                   │ │
│ │ WIN Holding Group — HR Portal                       │ │
│ └─────────────────────────────────────────────────────┘ │
├─────────────────────────────────────────────────────────┤
│ CONTENT AREA                                            │
│                                                         │
│   ICON (38px emoji)                                    │
│   📊                                                    │
│                                                         │
│   TITLE (color-coded)                                  │
│   Your Leave Balance                                    │
│   (#2563eb blue)                                       │
│                                                         │
│   MAIN CONTENT                                          │
│   Dear Saif Ahmed,                                     │
│                                                         │
│   Here is your leave balance:                          │
│   ┌─────────────────────────────────────┐             │
│   │ Type      │ Remaining │ Details     │             │
│   ├─────────────────────────────────────┤             │
│   │ Annual    │ 15.0 days │ of 21       │             │
│   │ Sick      │ 9.0 days  │ of 10       │             │
│   └─────────────────────────────────────┘             │
│                                                         │
│   Additional help text...                              │
│                                                         │
├─────────────────────────────────────────────────────────┤
│ FOOTER                                                  │
│ Fotopia HR System — Automated reply                    │
│ For assistance: hr@fotopia.com                         │
│                                                         │
│ Reply-Token: &lt;fotopia-hr-agent-UUID@domain&gt;        │
└─────────────────────────────────────────────────────────┘
```

---

## Test Coverage Map

```mermaid
graph TD
    A["10 Main Security Tests"] --> B["Stage 1: Loop Detection"]
    A --> C["Stage 2: Identity Check"]
    A --> D["Stage 3: Rate Limit"]
    A --> E["Stages 4-5: Intent + Tool"]
    A --> F["Stage 6: Reply Headers"]
    
    B --> B1["test_auto_reply_header_skipped"]
    C --> C1["test_unregistered_sender_no_reply"]
    C --> C2["test_self_email_skipped"]
    D --> D1["test_rate_limit_blocks_reply"]
    
    E --> E1["test_leave_balance_keyword_routes_to_tool"]
    E --> E2["test_leave_status_keyword_routes_to_tool"]
    E --> E3["test_policy_question_returns_canned_response"]
    E --> E4["test_unknown_intent_returns_canned_response"]
    E --> E5["test_role_from_db_not_body"]
    
    F --> F1["test_reply_sets_in_reply_to_header"]
    
    A --> G["Intent Classification Tests"]
    G --> G1["test_leave_request_detected"]
    G --> G2["test_leave_cancellation_detected_before_request"]
    G --> G3["test_balance_keywords_detected"]
    G --> G4["test_arabic_balance_keyword"]
    
    A --> H["Handler Unit Tests"]
    H --> H1["test_balance_handler_formats_html_table"]
    H --> H2["test_status_handler_formats_status_badges"]
    H --> H3["test_leave_request_handler_asks_for_clarification"]
    H --> H4["test_cancellation_handler_redirects_to_portal"]
```

---

## Error Paths (Graceful Degradation)

```mermaid
graph TD
    A["Tool Execution"] --> B{Result.success?}
    
    B -->|TRUE| B1["Extract data"]
    B1 --> B2["Build success response"]
    B2 --> B3["✅ Send confirmation"]
    
    B -->|FALSE| C["Extract error message"]
    C --> D{Analyze error}
    
    D -->|weekend/working day| D1["Show: 'Dates fall on weekend'"]
    D -->|balance/insufficient| D2["Show: 'Insufficient leave'"]
    D -->|threshold/cap/policy| D3["Show: 'Policy constraint'"]
    D -->|unknown error| D4["Show: 'Contact HR'"]
    
    D1 --> D5["⚠️ Build error response"]
    D2 --> D5
    D3 --> D5
    D4 --> D5
    D5 --> D6["Send with red banner"]
    
    D6 --> D7["Include HR email link"]
    
    B3 --> END["✅ Response sent"]
    D7 --> END
    
    style B3 fill:#c8e6c9
    style D5 fill:#ffebee
    style D7 fill:#fff3e0
```

---

## Multi-Language Support (Future-Ready)

```mermaid
graph TD
    A["Email arrives"] --> B["Extract tenant_id"]
    B --> C["DB: SELECT preferred_language<br/>FROM tenant_settings"]
    C --> D{Language<br/>supported?}
    
    D -->|English| D1["Use English templates"]
    D -->|Arabic| D2["Use Arabic templates"]
    D -->|Other| D3["Default to English"]
    
    D1 --> E["_handle_*() builds response<br/>in selected language"]
    D2 --> E
    D3 --> E
    
    E --> F["HTML: Include lang='en'<br/>or lang='ar'"]
    F --> G["Send branded reply"]
    
    note1["Keywords already<br/>support Arabic:<br/>رصيد, إجازة, إلغاء"]
```

