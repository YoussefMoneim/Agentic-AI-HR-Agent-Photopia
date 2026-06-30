from abc import ABC, abstractmethod


class DataSource(ABC):

    # ─── Existing read methods ─────────────────────────────────────────────────

    @abstractmethod
    def find_employees_by_name(self, tenant_id: str, name: str) -> list[dict]: ...

    @abstractmethod
    def get_employee_by_code(self, tenant_id: str, employee_code: str) -> dict | None: ...

    @abstractmethod
    def get_leave_balance(self, tenant_id: str, employee_code: str) -> int | None:
        """Legacy: returns annual_leave_balance integer from employees table.
        Kept for backward compatibility with the existing get_leave_balance tool."""

    @abstractmethod
    def get_employee_document_history(self, tenant_id: str, employee_code: str) -> list[dict]:
        """Returns audit_log rows for document tools for this employee, newest first."""

    @abstractmethod
    def list_employees(self, tenant_id: str, department: str | None) -> list[dict]:
        """Return up to 201 rows for truncation detection, filtered by department (case-insensitive) if provided.
        Returns non-salary fields only: employee_code, full_name, position, department,
        employment_type, email, manager_name."""

    # ─── Leave: read methods ───────────────────────────────────────────────────

    @abstractmethod
    def get_leave_types(self, tenant_id: str) -> list[dict]:
        """Return all active leave types for this tenant."""

    @abstractmethod
    def get_leave_balance_detail(self, tenant_id: str, employee_code: str, year: int) -> list[dict]:
        """Return leave balance rows for all tracked types for this employee in the given year.
        Each row: {leave_type_code, name_en, allocated_days, used_days, pending_days,
                   carry_over_days, balance_days}."""

    @abstractmethod
    def get_leave_requests(
        self, tenant_id: str, employee_code: str | None, status: str | None
    ) -> list[dict]:
        """Return leave requests, optionally filtered by employee_code and/or status.
        Newest first. Each row includes employee name and leave type name."""

    @abstractmethod
    def get_leave_policies(
        self, tenant_id: str, department: str | None, employee_code: str | None
    ) -> list[dict]:
        """Return active policy rules that apply to this employee: public rules +
        department-scoped rules for their department + employee-specific rules."""

    @abstractmethod
    def get_employee_manager(self, tenant_id: str, employee_code: str) -> dict | None:
        """Return the manager's {full_name, email, employee_code, id} or None if no manager is set."""

    @abstractmethod
    def get_pending_approvals(self, tenant_id: str, approver_employee_code: str) -> list[dict]:
        """Return pending_actions assigned to this approver, joined with leave request details."""

    @abstractmethod
    def get_pending_action_by_outbound_message_id(
        self, tenant_id: str, outbound_message_id: str
    ) -> dict | None:
        """Look up a pending_action by SMTP Message-ID stored at send time.
        Returns dict with: id, correlation_token, status, assigned_to_email,
        assigned_to_employee_id, deadline_at, workflow_instance_id.
        Returns None if not found."""

    @abstractmethod
    def get_leave_type_by_code(self, tenant_id: str, code: str) -> dict | None:
        """Return a single active leave_type row by code, including is_time_based and requires_hr_review."""

    @abstractmethod
    def get_leave_policy(self, tenant_id: str, leave_type_id: str) -> dict | None:
        """Return the flat leave_policies row for this (tenant, leave_type), or None if no policy exists."""

    @abstractmethod
    def get_leave_request_by_id(self, tenant_id: str, request_id: str) -> dict | None:
        """Return a leave_request row joined with employee and leave_type details, or None."""

    @abstractmethod
    def get_leave_requests_for_employee(
        self,
        tenant_id: str,
        employee_id: str,
        status: str | None = None,
        limit: int = 10,
    ) -> list[dict]:
        """Return leave requests for an employee (by DB UUID), newest first.
        Includes leave_type_name, manager name, and time fields for permission type."""

    @abstractmethod
    def get_pending_approvals_for_manager(
        self, tenant_id: str, manager_employee_id: str
    ) -> list[dict]:
        """Return leave_requests where manager_id = manager_employee_id and status = pending_approval.
        Includes employee name, leave type name, dates, and days_requested."""

    @abstractmethod
    def check_leave_overlap(
        self,
        tenant_id: str,
        employee_id: str,
        start_date: str,
        end_date: str,
        exclude_request_id: str | None = None,
    ) -> bool:
        """Return True if an overlapping approved/pending_approval date-based request exists for this employee."""

    @abstractmethod
    def get_wfh_usage(
        self,
        tenant_id: str,
        employee_id: str,
        week_start: str,
        month: int,
        year: int,
    ) -> dict:
        """Return {days_this_week, days_this_month} counting approved+pending WFH requests.
        week_start is the ISO date string of the Monday of the target week."""

    # ─── Leave: write methods ──────────────────────────────────────────────────

    @abstractmethod
    def create_leave_request(self, tenant_id: str, data: dict) -> dict:
        """Insert a leave_requests row and increment leave_balances.pending_days.
        data keys: employee_code, leave_type_code, start_date, end_date, days_requested, reason.
        Returns the created row with id."""

    @abstractmethod
    def create_workflow_instance(self, tenant_id: str, data: dict) -> dict:
        """Insert a workflow_instances row.
        data keys: workflow_type, subject_employee_code, triggered_by_user_id,
                   leave_request_id, current_step, state_snapshot.
        Returns the created row with id."""

    @abstractmethod
    def create_pending_action(self, tenant_id: str, data: dict) -> dict:
        """Insert a pending_actions row (idempotency_key is unique — raises on duplicate).
        data keys: workflow_instance_id, action_type, assigned_to_employee_code,
                   assigned_to_email, correlation_token, context_snapshot, prompt_text,
                   deadline_at, idempotency_key.
        Returns the created row with id and correlation_token."""

    @abstractmethod
    def link_leave_request_to_workflow(
        self, tenant_id: str, leave_request_id: str, workflow_instance_id: str
    ) -> bool:
        """Set leave_requests.workflow_instance_id and update workflow_instances.leave_request_id."""

    @abstractmethod
    def resolve_pending_action(
        self,
        tenant_id: str,
        correlation_token: str,
        decision: str,
        resolved_by_code: str | None,
        note: str | None,
    ) -> dict:
        """Atomically: update pending_action status, leave_request status, workflow status,
        and adjust leave_balances (approved: pending→used; rejected: pending→freed).
        Returns {success, decision, leave_request_id, employee_code, days_requested}."""

    @abstractmethod
    def update_leave_balance(
        self,
        tenant_id: str,
        employee_id: str,
        leave_type_id: str,
        year: int,
        delta_pending: float = 0.0,
        delta_used: float = 0.0,
    ) -> bool:
        """Atomically adjust leave_balances. All decrements use GREATEST(0, ...) guard.
        Use negative deltas to release days (e.g. rejection: delta_pending=-days)."""

    @abstractmethod
    def update_leave_request_status(
        self,
        tenant_id: str,
        request_id: str,
        new_status: str,
        metadata: dict,
    ) -> bool:
        """Update leave_requests.status and optional metadata fields.
        metadata keys (all optional): manager_comment, manager_decision_at,
        hr_comment, hr_decision_at, hr_reviewer_id, resolved_by_id, rejection_reason."""

    # ─── Workflow events ───────────────────────────────────────────────────────

    @abstractmethod
    def create_workflow_event(
        self,
        tenant_id: str,
        workflow_instance_id: str | None,
        event_type: str,
        actor_employee_id: str | None,
        actor_user_id: str | None,
        data: dict,
    ) -> dict:
        """Insert a workflow_events row and return it.
        event_type: 'submitted' | 'pending_approval_sent' | 'manager_approved'
                  | 'manager_rejected' | 'top_of_hierarchy_approved'
                  | 'cancelled' | 'completed' | 'timed_out'"""

    @abstractmethod
    def sync_workflow_decision(
        self,
        tenant_id: str,
        leave_request_id: str,
        decision: str,
        actor_employee_id: str | None,
        actor_user_id: str | None,
        resolution_note: str | None,
    ) -> bool:
        """Atomically close the active pending_action + workflow_instance for a leave request
        after a tool-based approve/reject, and write a workflow_events row.
        decision: 'approved' | 'rejected'
        Returns True if a pending_action was found and updated, False if no active action existed."""

    @abstractmethod
    def get_tenant_settings(self, tenant_id: str) -> dict:
        """Return tenants.settings JSONB for the given tenant, or {} if not found."""

    @abstractmethod
    def count_active_leaves_in_department(
        self,
        tenant_id: str,
        department: str,
        start_date: str,
        end_date: str,
        exclude_request_id: str | None = None,
    ) -> dict:
        """Return {"active_count": int, "total_employees": int} for the department
        during the date range. active_count excludes exclude_request_id if provided."""

    @abstractmethod
    def record_appropriateness_decision(
        self,
        tenant_id: str,
        event_id: str,
        decision: str,
    ) -> None:
        """Set workflow_events.data.human_decision for the given event.
        decision: 'proceeded' | 'cancelled'"""

    @abstractmethod
    def count_leave_type_usage(
        self, tenant_id: str, employee_id: str, leave_type_code: str
    ) -> int:
        """Count non-rejected, non-cancelled leave requests for this employee and leave type.
        Used to enforce max_times_in_career (e.g. marriage=1, hajj=1, maternity=3).
        Counts statuses: pending_approval, pending_top_of_hierarchy, manager_approved,
        hr_approved, completed. Excludes: manager_rejected, hr_rejected, cancelled, withdrawn."""

    @abstractmethod
    def get_employee_age(self, tenant_id: str, employee_id: str) -> int | None:
        """Return employee age in full years calculated from birth_date.
        Returns None if birth_date is NULL. Used for age ≥50 → 30-day annual leave advisory."""

    @abstractmethod
    def add_compensatory_day(
        self,
        tenant_id: str,
        employee_id: str,
        holiday_date: str,
        approved_by_employee_id: str,
    ) -> dict:
        """Credit 1 day to the employee's annual leave balance as compensatory off for working
        on a public holiday or weekend. holiday_date is an ISO date string of the day worked.
        approved_by_employee_id is the UUID of the manager who pre-approved the work.
        Returns {success, new_allocated_days, leave_balance_id}."""

    # ─── Leave: cancellation methods ──────────────────────────────────────────

    @abstractmethod
    def request_leave_cancellation(
        self,
        tenant_id: str,
        leave_request_id: str,
        requesting_employee_id: str,
        reason: str | None,
    ) -> dict:
        """Atomically set status=cancellation_pending and record the cancellation request.
        Verifies status is manager_approved or hr_approved before updating.
        Returns {success, leave_request_id, employee_name, leave_type, start_date, end_date}."""

    @abstractmethod
    def approve_leave_cancellation(
        self,
        tenant_id: str,
        leave_request_id: str,
        decided_by_employee_id: str,
        consumed_days: float | None,
    ) -> dict:
        """Atomically approve a cancellation_pending leave request.
        Calculates days_to_restore:
          - If consumed_days provided: days_to_restore = days_requested - consumed_days
          - elif start_date > today: full restore (days_to_restore = days_requested)
          - elif end_date < today: 0 (fully consumed)
          - else (in progress, no consumed_days): 0 (conservative)
        Updates leave_requests status=cancelled and restores used_days in leave_balances
        using GREATEST(0, used_days - days_to_restore) to prevent negatives.
        Returns {success, days_restored, new_used_days, employee_name, leave_type}."""

    @abstractmethod
    def get_pending_cancellations(self, tenant_id: str) -> list[dict]:
        """Return leave_requests with status=cancellation_pending for this tenant,
        ordered by cancellation_requested_at ASC (oldest first).
        Each row includes: id, employee_name, leave_type_name, start_date, end_date,
        days_requested, cancellation_reason, cancellation_requested_at."""

    @abstractmethod
    def get_leave_request_by_token(self, tenant_id: str, correlation_token: str) -> dict | None:
        """Return the enriched leave request (same shape as get_leave_request_by_id) for the
        pending_action identified by correlation_token, plus two extra keys:
          approver_employee_code — the manager's employee_code
          approver_role          — the manager's role (falls back to 'hr_manager' if NULL)
        Returns None if the token is not found or the action is already resolved.
        Used to run evaluate_constraints() BEFORE resolve_pending_action() in the email-link path."""

    @abstractmethod
    def get_team_calendar(
        self,
        tenant_id: str,
        caller_role: str,
        caller_employee_id: str,
        year: int,
        month: int,
        department: str | None = None,
    ) -> dict:
        """Return team leave calendar data for the given month, role-scoped.

        events — role-scoped:
          employee  → only caller's own leave requests
          manager   → direct reports (employees WHERE manager_id = caller_employee_id)
          hr/admin  → all employees (optionally filtered by department)

        daily_summary — always built from all employees in the tenant (or filtered dept)
          so an employee sees meaningful team-wide counts without seeing names.

        Privacy: employee_name / employee_code / leave_type_* are None for events
        where is_own=False and caller_role is 'employee'.

        Returns {events, daily_summary, departments, total_employees_in_scope}."""

    # ─── RAG / policy search ───────────────────────────────────────────────────

    @abstractmethod
    def search_policy(
        self,
        tenant_id: str,
        query: str,
        caller_roles: list[str],
        limit: int = 5,
    ) -> list[dict]:
        """Full-text search over private_document_chunks.
        Pre-filters allowed_roles && caller_roles BEFORE text search — never post-filter.
        classified_at IS NOT NULL guard ensures quarantine chunks are never returned.
        Returns list of {document_id, chunk_index, content, source_file, sensitivity}."""

    # ─── Email agent ──────────────────────────────────────────────────────────

    @abstractmethod
    def get_employee_by_email(self, tenant_id: str, email: str) -> dict | None:
        """Return employee row matching work email (case-insensitive), or None.
        Joins users to get the authoritative role (defaults to 'employee' if no user record).
        Returns: {id, employee_code, full_name, email, notification_email,
                  department, position, role}"""

    @abstractmethod
    def check_and_record_rate_limit(
        self,
        tenant_id: str,
        sender_email: str,
        max_per_hour: int = 5,
        block_minutes: int = 60,
    ) -> dict:
        """Check and record rate limit for sender in email_agent_rate_limit.
        Returns: {"allowed": bool, "count": int, "blocked_until": str | None}
        Resets window after 1 hour. Blocks sender for block_minutes when count > max_per_hour."""
