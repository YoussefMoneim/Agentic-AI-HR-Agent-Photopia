# Governance and Audit
**Tier:** Enterprise | **Owner:** HR + Legal + Finance | **Version:** 1.0 | **Review:** Annual  
*Access: HR managers, administrators only*

---

## 1. HR Audit Schedule
- **Annual:** Full headcount and payroll audit (Finance + HR). Reconcile headcount across departments against budget. Reconcile payroll to social insurance records.
- **Semi-annual:** Access rights review. HR reviews all system permissions and tool access; removes access for leavers and adjusts for role changes.
- **Annual:** Policy compliance review. HR reviews adherence to all active policies; reports findings to HR Director.

## 2. Approval Authority Matrix

| Action | Authorized By |
|---|---|
| New hire offer (up to Grade 5) | Hiring Manager + HR |
| New hire offer (Grade 6+) | Department Head + HR Director |
| Salary increase | Manager + HR (within budget envelope) |
| Salary increase above band maximum | Finance Director + HR Director |
| Summary dismissal | HR Director + Legal |
| Redundancy | HR Director + CEO |
| Policy change | HR Director (minor) / HR Director + CEO (major) |

## 3. Segregation of Duties
No single person may both initiate and approve a significant HR action. Specific controls: the person raising a headcount request cannot approve it; the person preparing a final pay calculation cannot authorize its payment; the person conducting a disciplinary investigation cannot decide its outcome. Self-approval is only permitted at the CEO level and must be explicitly flagged and logged.

## 4. Record Retention
- Employee HR file: minimum 5 years after departure
- Payroll records: minimum 10 years
- Disciplinary records: minimum 5 years after departure
- Recruitment records (unsuccessful candidates): 1 year (PDPL minimum)
- Secure destruction: physical files shredded; digital files deleted with IT sign-off

## 5. Policy Review Cycle
All policies are reviewed annually by the policy owner. Material changes require HR Director approval and communication to all affected employees. Version control is maintained in the HR document management system. Employees are notified of policy changes via email with a 20-day notice period before the change takes effect.

## 6. External Reporting Obligations
- **Labour Office:** Annual workforce statistics reports as required by Egyptian Labour Law
- **Social Insurance Authority:** Monthly contribution submissions; new hire and leaver notifications within the legal window
- **NTRA:** Data breach notifications within 72 hours where required under PDPL

---

# Agentic System Governance
**Tier:** Enterprise | **Owner:** HR + IT + Legal | **Version:** 1.0 | **Review:** Quarterly  
*Access: HR managers, administrators only*

This policy governs the use of AI agent systems (including the Fotopia HR Agent) for HR actions.

---

## 1. Agent Identity and Minimum Privilege
Every AI agent has its own identity, separate from the human user who invoked it. The agent does not inherit the user's full permissions. Each agent is granted only the specific tools and data access required for its designated function. Access is provisioned just-in-time and revoked after the task.

## 2. Human-in-the-Loop Requirements

| Action Category | Requirement |
|---|---|
| Read-only queries (employee data, leave balance) | Agent may execute autonomously |
| Draft document generation | Agent drafts; human reviews and approves before finalising |
| Leave request submission | Agent submits; manager approves via the approval queue |
| Leave request approval/rejection | Human approves/rejects via the approval queue; agent cannot auto-approve |
| Payroll changes, contract generation | Human approval required before any state change |
| Government filing (social insurance, tax) | Human authorization required; agent cannot file autonomously |
| Termination actions | HR Director sign-off required; agent cannot execute |

## 3. Audit Trail Requirements
Every agent action is logged with: the human user on whose behalf it acted, the agent identity, the tool called, the input parameters, the authorization decision and reason, the output, and the timestamp. Audit logs are append-only and may not be modified by any user or agent. Audit logs for regulated actions are retained for a minimum of 7 years.

## 4. Data Access Controls
- **Role-scoped tool catalog:** The agent only sees tools the invoking user's role permits. It cannot call tools outside its catalog regardless of what the user requests.
- **Field-level masking:** Salary, national ID, and other sensitive fields are masked for roles below HR Manager level — even when the agent is acting on their behalf. The masked value is never visible to the agent or returned in any response.
- **Tenant isolation:** The agent can never access data belonging to a different tenant under any circumstance. Row-level security in the database enforces this independently of application logic.

## 5. Appropriateness Flagging
The agent is configured to flag situations where a technically-permitted action may be inappropriate — for example, sharing a document containing sensitive information with a broader audience than its classification warrants. When the agent flags an appropriateness concern: it presents the concern to the human with a plain-language explanation; the human has final say and may proceed or stop; both the flag and the human's decision are recorded in the audit log. The agent does not block on appropriateness grounds — it informs and records.

## 6. Constraint Engine — Hard and Soft Rules
The agent enforces two classes of deterministic rules independently of LLM reasoning:

**Hard rules (cannot be overridden):** Where an action is prohibited by Egyptian law or a legal obligation, the agent blocks it and explains why. Example: rejecting sick leave backed by a valid medical certificate. No user — regardless of seniority — can override a hard rule through the agent.

**Soft rules (overridable with authority and justification):** Where an action exceeds a policy threshold, the agent warns the authorized user, requires an explicit override reason, and logs the exception. Example: approving leave that would result in more than 25% of a department absent simultaneously. Only HR managers and administrators may provide overrides.

## 7. Incident Response
If an agent behaves unexpectedly, produces an incorrect result, or takes an unauthorized action: (1) The HR Director may suspend the agent system immediately via the admin panel. (2) IT Security investigates the root cause within 24 hours. (3) All actions taken by the agent during the incident period are reviewed; incorrect state changes are rolled back where technically possible. (4) A post-incident report is issued to the HR Director and Legal within 5 working days.

## 8. Prohibition on Fully Autonomous High-Blast-Radius Actions
The agent must never: send mass communications without human approval; modify payroll without Finance and HR sign-off; generate or sign contracts autonomously; file with government authorities; or access email inboxes other than the designated workflow inbox. These prohibitions apply regardless of what any user instructs the agent, and cannot be lifted by any single approver.
