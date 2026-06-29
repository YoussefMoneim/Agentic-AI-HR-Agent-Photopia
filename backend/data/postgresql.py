import json
from datetime import date, datetime, timezone

import psycopg2
from psycopg2.extras import RealDictCursor

from data.base import DataSource


def _isodate(val) -> str | None:
    if val is None:
        return None
    if isinstance(val, (date, datetime)):
        return val.isoformat()
    return val


def _float(val) -> float | None:
    if val is None:
        return None
    return float(val)


class PostgreSQLDataSource(DataSource):
    def __init__(self, database_url: str) -> None:
        self._database_url = database_url

    def _conn(self):
        return psycopg2.connect(self._database_url)

    def _release(self, conn):
        conn.close()

    def _set_tenant(self, conn, tenant_id: str) -> None:
        """Switch to the non-superuser app role and set the RLS tenant variable.
        Superusers are exempt from RLS; SET ROLE drops that exemption for this session."""
        with conn.cursor() as cur:
            cur.execute("SET ROLE fotopia_app")
            cur.execute("SET app.current_tenant_id = %s", (tenant_id,))

    # ─── Existing read methods ─────────────────────────────────────────────────

    def find_employees_by_name(self, tenant_id: str, name: str) -> list[dict]:
        conn = self._conn()
        try:
            self._set_tenant(conn, tenant_id)
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    """
                    SELECT id, employee_code, full_name, arabic_name, position, department,
                           employment_type, currency, annual_leave_balance, email, manager_name
                    FROM employees
                    WHERE tenant_id = %s
                      AND full_name ILIKE %s
                    ORDER BY full_name
                    """,
                    (tenant_id, f"%{name}%"),
                )
                return [dict(row) for row in cur.fetchall()]
        finally:
            self._release(conn)

    def get_employee_by_code(self, tenant_id: str, employee_code: str) -> dict | None:
        conn = self._conn()
        try:
            self._set_tenant(conn, tenant_id)
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    """
                    SELECT id, employee_code, full_name, arabic_name, position, department,
                           employment_type, start_date, basic_salary, housing_allowance,
                           transport_allowance, total_salary, currency, annual_leave_balance,
                           email, manager_name, manager_id
                    FROM employees
                    WHERE tenant_id = %s
                      AND employee_code = %s
                    """,
                    (tenant_id, employee_code),
                )
                row = cur.fetchone()
                if row is None:
                    return None
                result = dict(row)
                result["start_date"] = _isodate(result.get("start_date"))
                result["id"] = str(result["id"]) if result.get("id") else None
                result["manager_id"] = str(result["manager_id"]) if result.get("manager_id") else None
                for field in ("basic_salary", "housing_allowance", "transport_allowance", "total_salary"):
                    result[field] = _float(result.get(field))
                return result
        finally:
            self._release(conn)

    def get_leave_balance(self, tenant_id: str, employee_code: str) -> int | None:
        conn = self._conn()
        try:
            self._set_tenant(conn, tenant_id)
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT annual_leave_balance
                    FROM employees
                    WHERE tenant_id = %s
                      AND employee_code = %s
                    """,
                    (tenant_id, employee_code),
                )
                row = cur.fetchone()
                return row[0] if row else None
        finally:
            self._release(conn)

    def list_employees(self, tenant_id: str, department: str | None) -> list[dict]:
        conn = self._conn()
        try:
            self._set_tenant(conn, tenant_id)
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    """
                    SELECT employee_code, full_name, position, department,
                           employment_type, email, manager_name
                    FROM employees
                    WHERE tenant_id = %s
                      AND (%s IS NULL OR LOWER(department) = LOWER(%s))
                    ORDER BY full_name
                    LIMIT 201
                    """,
                    (tenant_id, department, department),
                )
                return [dict(row) for row in cur.fetchall()]
        finally:
            self._release(conn)

    def get_employee_document_history(self, tenant_id: str, employee_code: str) -> list[dict]:
        conn = self._conn()
        try:
            self._set_tenant(conn, tenant_id)
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    """
                    SELECT tool_name, outcome, result_summary, created_at
                    FROM audit_log
                    WHERE tenant_id = %s
                      AND tool_name IN (
                          'generate_salary_certificate',
                          'generate_twimc_letter',
                          'generate_experience_certificate'
                      )
                      AND tool_input->>'employee_code' = %s
                    ORDER BY created_at DESC
                    """,
                    (tenant_id, employee_code),
                )
                rows = []
                for row in cur.fetchall():
                    r = dict(row)
                    r["created_at"] = _isodate(r.get("created_at"))
                    rows.append(r)
                return rows
        finally:
            self._release(conn)

    # ─── Leave: read methods ───────────────────────────────────────────────────

    def get_leave_types(self, tenant_id: str) -> list[dict]:
        conn = self._conn()
        try:
            self._set_tenant(conn, tenant_id)
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    """
                    SELECT id, code, name_en, name_ar, requires_approval,
                           requires_documentation, deducts_balance,
                           max_days_per_year, max_consecutive_days
                    FROM leave_types
                    WHERE tenant_id = %s AND is_active = TRUE
                    ORDER BY code
                    """,
                    (tenant_id,),
                )
                rows = []
                for row in cur.fetchall():
                    r = dict(row)
                    r["id"] = str(r["id"])
                    rows.append(r)
                return rows
        finally:
            self._release(conn)

    def get_leave_balance_detail(self, tenant_id: str, employee_code: str, year: int) -> list[dict]:
        conn = self._conn()
        try:
            self._set_tenant(conn, tenant_id)
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    """
                    SELECT lt.code AS leave_type_code,
                           lt.name_en,
                           lb.allocated_days,
                           lb.used_days,
                           lb.pending_days,
                           lb.carry_over_days,
                           (lb.allocated_days - lb.used_days - lb.pending_days + lb.carry_over_days) AS balance_days
                    FROM leave_balances lb
                    JOIN leave_types lt ON lt.id = lb.leave_type_id
                    JOIN employees e ON e.id = lb.employee_id
                    WHERE lb.tenant_id = %s
                      AND e.employee_code = %s
                      AND lb.year = %s
                    ORDER BY lt.code
                    """,
                    (tenant_id, employee_code, year),
                )
                rows = []
                for row in cur.fetchall():
                    r = dict(row)
                    for f in ("allocated_days", "used_days", "pending_days", "carry_over_days", "balance_days"):
                        r[f] = _float(r.get(f))
                    rows.append(r)
                return rows
        finally:
            self._release(conn)

    def get_leave_requests(
        self, tenant_id: str, employee_code: str | None, status: str | None
    ) -> list[dict]:
        conn = self._conn()
        try:
            self._set_tenant(conn, tenant_id)
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    """
                    SELECT lr.id,
                           e.employee_code,
                           e.full_name AS employee_name,
                           lt.code AS leave_type_code,
                           lt.name_en AS leave_type_name,
                           lr.start_date,
                           lr.end_date,
                           lr.days_requested,
                           lr.reason,
                           lr.status,
                           lr.rejection_reason,
                           lr.submitted_at,
                           lr.resolved_at
                    FROM leave_requests lr
                    JOIN employees e ON e.id = lr.employee_id
                    JOIN leave_types lt ON lt.id = lr.leave_type_id
                    WHERE lr.tenant_id = %s
                      AND (%s IS NULL OR e.employee_code = %s)
                      AND (%s IS NULL OR lr.status = %s)
                    ORDER BY lr.submitted_at DESC
                    LIMIT 50
                    """,
                    (tenant_id, employee_code, employee_code, status, status),
                )
                rows = []
                for row in cur.fetchall():
                    r = dict(row)
                    r["id"] = str(r["id"])
                    r["start_date"] = _isodate(r.get("start_date"))
                    r["end_date"] = _isodate(r.get("end_date"))
                    r["submitted_at"] = _isodate(r.get("submitted_at"))
                    r["resolved_at"] = _isodate(r.get("resolved_at"))
                    r["days_requested"] = _float(r.get("days_requested"))
                    rows.append(r)
                return rows
        finally:
            self._release(conn)

    def get_leave_policies(
        self, tenant_id: str, department: str | None, employee_code: str | None
    ) -> list[dict]:
        # The flat schema has one row per (tenant, leave_type) — no scope/department/employee columns.
        # department and employee_code params are kept for interface compatibility but are not used.
        conn = self._conn()
        try:
            self._set_tenant(conn, tenant_id)
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    """
                    SELECT lp.id,
                           lt.code AS leave_type_code,
                           lt.name_en AS leave_type_name,
                           lp.probation_restriction_days,
                           lp.annual_allowance_days,
                           lp.wfh_max_days_per_week,
                           lp.wfh_max_days_per_month,
                           lp.max_consecutive_days,
                           lp.requires_medical_cert_after_days,
                           lp.min_notice_days
                    FROM leave_policies lp
                    JOIN leave_types lt ON lt.id = lp.leave_type_id
                    WHERE lp.tenant_id = %s
                    ORDER BY lt.code
                    """,
                    (tenant_id,),
                )
                rows = []
                for row in cur.fetchall():
                    r = dict(row)
                    r["id"] = str(r["id"])
                    r["annual_allowance_days"] = _float(r.get("annual_allowance_days"))
                    rows.append(r)
                return rows
        finally:
            self._release(conn)

    def get_employee_manager(self, tenant_id: str, employee_code: str) -> dict | None:
        conn = self._conn()
        try:
            self._set_tenant(conn, tenant_id)
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    """
                    SELECT mgr.id, mgr.employee_code, mgr.full_name, mgr.email, mgr.notification_email
                    FROM employees e
                    JOIN employees mgr ON mgr.id = e.manager_id
                    WHERE e.tenant_id = %s
                      AND e.employee_code = %s
                      AND e.manager_id IS NOT NULL
                    """,
                    (tenant_id, employee_code),
                )
                row = cur.fetchone()
                if row is None:
                    return None
                r = dict(row)
                r["id"] = str(r["id"])
                return r
        finally:
            self._release(conn)

    def get_pending_approvals(self, tenant_id: str, approver_employee_code: str) -> list[dict]:
        conn = self._conn()
        try:
            self._set_tenant(conn, tenant_id)
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    """
                    SELECT pa.id,
                           pa.correlation_token,
                           pa.status,
                           pa.assigned_to_email,
                           pa.sent_at,
                           pa.deadline_at,
                           e.full_name AS employee_name,
                           e.employee_code,
                           lt.name_en AS leave_type_name,
                           lr.id         AS leave_request_id,
                           lr.start_date,
                           lr.end_date,
                           lr.days_requested,
                           lr.reason,
                           lr.submitted_at,
                           lr.status AS request_status,
                           COALESCE(lb.allocated_days, 0)
                             + COALESCE(lb.carry_over_days, 0)
                             - COALESCE(lb.used_days, 0)
                             - COALESCE(lb.pending_days, 0) AS balance_remaining
                    FROM pending_actions pa
                    JOIN workflow_instances wi ON wi.id = pa.workflow_instance_id
                    JOIN employees approver ON approver.id = pa.assigned_to_employee_id
                    LEFT JOIN leave_requests lr ON lr.id = wi.leave_request_id::uuid
                    LEFT JOIN employees e ON e.id = wi.subject_employee_id
                    LEFT JOIN leave_types lt ON lt.id = lr.leave_type_id
                    LEFT JOIN leave_balances lb
                           ON lb.employee_id   = e.id
                          AND lb.leave_type_id = lr.leave_type_id
                          AND lb.year          = EXTRACT(YEAR FROM lr.start_date)::int
                          AND lb.tenant_id     = pa.tenant_id
                    WHERE pa.tenant_id = %s
                      AND approver.employee_code = %s
                      AND pa.status = 'pending'
                    ORDER BY pa.sent_at DESC
                    """,
                    (tenant_id, approver_employee_code),
                )
                rows = []
                for row in cur.fetchall():
                    r = dict(row)
                    r["id"] = str(r["id"])
                    r["leave_request_id"] = str(r["leave_request_id"]) if r.get("leave_request_id") else None
                    r["start_date"] = _isodate(r.get("start_date"))
                    r["end_date"] = _isodate(r.get("end_date"))
                    r["sent_at"] = _isodate(r.get("sent_at"))
                    r["deadline_at"] = _isodate(r.get("deadline_at"))
                    r["submitted_at"] = _isodate(r.get("submitted_at"))
                    r["days_requested"] = _float(r.get("days_requested"))
                    r["balance_remaining"] = _float(r.get("balance_remaining"))
                    rows.append(r)
                return rows
        finally:
            self._release(conn)

    def get_pending_action_by_outbound_message_id(
        self, tenant_id: str, outbound_message_id: str
    ) -> dict | None:
        conn = self._conn()
        try:
            self._set_tenant(conn, tenant_id)
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    """
                    SELECT id, correlation_token, status, assigned_to_email,
                           assigned_to_employee_id, deadline_at, workflow_instance_id
                    FROM pending_actions
                    WHERE tenant_id = %s AND outbound_message_id = %s
                    """,
                    (tenant_id, outbound_message_id),
                )
                row = cur.fetchone()
            if row is None:
                return None
            r = dict(row)
            r["id"] = str(r["id"])
            r["assigned_to_employee_id"] = (
                str(r["assigned_to_employee_id"]) if r.get("assigned_to_employee_id") else None
            )
            r["workflow_instance_id"] = (
                str(r["workflow_instance_id"]) if r.get("workflow_instance_id") else None
            )
            r["deadline_at"] = _isodate(r.get("deadline_at"))
            return r
        finally:
            self._release(conn)

    # ─── Leave: write methods ──────────────────────────────────────────────────

    def create_leave_request(self, tenant_id: str, data: dict) -> dict:
        conn = self._conn()
        try:
            self._set_tenant(conn, tenant_id)
            with conn:
                with conn.cursor(cursor_factory=RealDictCursor) as cur:
                    # Resolve employee_code → id
                    cur.execute(
                        "SELECT id FROM employees WHERE tenant_id = %s AND employee_code = %s",
                        (tenant_id, data["employee_code"]),
                    )
                    emp_row = cur.fetchone()
                    if emp_row is None:
                        raise ValueError(f"Employee {data['employee_code']} not found")
                    employee_id = emp_row["id"]

                    # Resolve leave_type_code → id
                    cur.execute(
                        "SELECT id, deducts_balance FROM leave_types WHERE tenant_id = %s AND code = %s",
                        (tenant_id, data["leave_type_code"]),
                    )
                    lt_row = cur.fetchone()
                    if lt_row is None:
                        raise ValueError(f"Leave type {data['leave_type_code']} not found")
                    leave_type_id = lt_row["id"]
                    deducts_balance = lt_row["deducts_balance"]

                    # Resolve manager_code → id if provided
                    manager_id = None
                    if data.get("manager_id"):
                        manager_id = data["manager_id"]  # already a UUID string from submit tool
                    elif data.get("manager_code"):
                        cur.execute(
                            "SELECT id FROM employees WHERE tenant_id = %s AND employee_code = %s",
                            (tenant_id, data["manager_code"]),
                        )
                        mgr_row = cur.fetchone()
                        manager_id = mgr_row["id"] if mgr_row else None

                    cur.execute(
                        """
                        INSERT INTO leave_requests
                            (tenant_id, employee_id, leave_type_id,
                             start_date, end_date, days_requested,
                             start_datetime, end_datetime, duration_hours,
                             reason, attachment_path, manager_id, is_casual)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        RETURNING id, status, submitted_at
                        """,
                        (
                            tenant_id, employee_id, leave_type_id,
                            data.get("start_date"), data.get("end_date"),
                            data.get("days_requested"),
                            data.get("start_datetime"), data.get("end_datetime"),
                            data.get("duration_hours"),
                            data.get("reason"), data.get("attachment_path"),
                            manager_id, bool(data.get("is_casual", False)),
                        ),
                    )
                    row = cur.fetchone()
                    result = dict(row)
                    result["id"] = str(result["id"])
                    result["submitted_at"] = _isodate(result.get("submitted_at"))

                    # Reserve pending days in leave_balances (best-effort; no error if row missing)
                    ref_date = data.get("start_date") or (
                        data["start_datetime"][:10] if data.get("start_datetime") else None
                    )
                    if deducts_balance and data.get("days_requested") and ref_date:
                        cur.execute(
                            """
                            UPDATE leave_balances
                            SET pending_days = pending_days + %s, updated_at = now()
                            WHERE tenant_id = %s
                              AND employee_id = %s
                              AND leave_type_id = %s
                              AND year = EXTRACT(YEAR FROM %s::date)
                            """,
                            (
                                data["days_requested"], tenant_id, employee_id,
                                leave_type_id, ref_date,
                            ),
                        )

                    return result
        finally:
            self._release(conn)

    def create_workflow_instance(self, tenant_id: str, data: dict) -> dict:
        conn = self._conn()
        try:
            self._set_tenant(conn, tenant_id)
            with conn:
                with conn.cursor(cursor_factory=RealDictCursor) as cur:
                    # Resolve subject_employee_code → id
                    cur.execute(
                        "SELECT id FROM employees WHERE tenant_id = %s AND employee_code = %s",
                        (tenant_id, data["subject_employee_code"]),
                    )
                    emp_row = cur.fetchone()
                    subject_id = emp_row["id"] if emp_row else None

                    cur.execute(
                        """
                        INSERT INTO workflow_instances
                            (tenant_id, workflow_type, subject_employee_id,
                             triggered_by_user_id, leave_request_id, current_step,
                             status, state_snapshot)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                        RETURNING id, status, created_at
                        """,
                        (
                            tenant_id,
                            data.get("workflow_type", "leave_approval"),
                            subject_id,
                            data.get("triggered_by_user_id"),
                            data.get("leave_request_id"),
                            data["current_step"],
                            data.get("status", "waiting_human"),
                            json.dumps(data.get("state_snapshot", {})),
                        ),
                    )
                    row = cur.fetchone()
                    result = dict(row)
                    result["id"] = str(result["id"])
                    result["created_at"] = _isodate(result.get("created_at"))
                    return result
        finally:
            self._release(conn)

    def create_pending_action(self, tenant_id: str, data: dict) -> dict:
        conn = self._conn()
        try:
            self._set_tenant(conn, tenant_id)
            with conn:
                with conn.cursor(cursor_factory=RealDictCursor) as cur:
                    # Resolve assigned_to_employee_code → id
                    assigned_id = None
                    if data.get("assigned_to_employee_code"):
                        cur.execute(
                            "SELECT id FROM employees WHERE tenant_id = %s AND employee_code = %s",
                            (tenant_id, data["assigned_to_employee_code"]),
                        )
                        emp_row = cur.fetchone()
                        assigned_id = emp_row["id"] if emp_row else None

                    cur.execute(
                        """
                        INSERT INTO pending_actions
                            (id,
                             tenant_id, workflow_instance_id, action_type,
                             assigned_to_employee_id, assigned_to_email,
                             outbound_message_id,
                             correlation_token, context_snapshot, prompt_text,
                             deadline_at, idempotency_key)
                        VALUES (COALESCE(%s::uuid, gen_random_uuid()),
                                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        RETURNING id, correlation_token, outbound_message_id, sent_at, deadline_at
                        """,
                        (
                            data.get("pa_id"),
                            tenant_id,
                            data["workflow_instance_id"],
                            data.get("action_type", "email_approval"),
                            assigned_id,
                            data["assigned_to_email"],
                            data.get("outbound_message_id"),
                            data["correlation_token"],
                            json.dumps(data.get("context_snapshot", {})),
                            data["prompt_text"],
                            data["deadline_at"],
                            data["idempotency_key"],
                        ),
                    )
                    row = cur.fetchone()
                    result = dict(row)
                    result["id"] = str(result["id"])
                    result["sent_at"] = _isodate(result.get("sent_at"))
                    result["deadline_at"] = _isodate(result.get("deadline_at"))
                    return result
        finally:
            self._release(conn)

    def link_leave_request_to_workflow(
        self, tenant_id: str, leave_request_id: str, workflow_instance_id: str
    ) -> bool:
        conn = self._conn()
        try:
            self._set_tenant(conn, tenant_id)
            with conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        UPDATE leave_requests
                        SET workflow_instance_id = %s, updated_at = now()
                        WHERE tenant_id = %s AND id = %s
                        """,
                        (workflow_instance_id, tenant_id, leave_request_id),
                    )
                    cur.execute(
                        """
                        UPDATE workflow_instances
                        SET leave_request_id = %s, updated_at = now()
                        WHERE tenant_id = %s AND id = %s
                        """,
                        (leave_request_id, tenant_id, workflow_instance_id),
                    )
                    return True
        finally:
            self._release(conn)

    def resolve_pending_action(
        self,
        tenant_id: str,
        correlation_token: str,
        decision: str,
        resolved_by_code: str | None,
        note: str | None,
    ) -> dict:
        conn = self._conn()
        try:
            self._set_tenant(conn, tenant_id)
            with conn:
                with conn.cursor(cursor_factory=RealDictCursor) as cur:
                    # Resolve resolver employee_code → id
                    resolver_id = None
                    if resolved_by_code:
                        cur.execute(
                            "SELECT id FROM employees WHERE tenant_id = %s AND employee_code = %s",
                            (tenant_id, resolved_by_code),
                        )
                        r = cur.fetchone()
                        resolver_id = r["id"] if r else None

                    # Fetch the pending action
                    cur.execute(
                        """
                        SELECT pa.id, pa.workflow_instance_id, pa.status, pa.deadline_at,
                               wi.leave_request_id, wi.subject_employee_id
                        FROM pending_actions pa
                        JOIN workflow_instances wi ON wi.id = pa.workflow_instance_id
                        WHERE pa.tenant_id = %s
                          AND pa.correlation_token = %s
                        """,
                        (tenant_id, correlation_token),
                    )
                    pa = cur.fetchone()
                    if pa is None:
                        return {"success": False, "error": "Correlation token not found"}
                    if pa["status"] != "pending":
                        return {"success": False, "error": f"Already resolved: {pa['status']}"}
                    if pa.get("deadline_at") and pa["deadline_at"] < datetime.now(timezone.utc):
                        return {"success": False, "error": "This approval link has expired"}

                    workflow_id = pa["workflow_instance_id"]
                    leave_request_id = pa["leave_request_id"]
                    subject_employee_id = pa["subject_employee_id"]

                    # Update pending_action
                    cur.execute(
                        """
                        UPDATE pending_actions
                        SET status = %s, resolved_at = now(),
                            resolved_by_employee_id = %s, resolution_note = %s
                        WHERE id = %s
                        """,
                        (decision, resolver_id, note, pa["id"]),
                    )

                    # Update workflow_instance
                    cur.execute(
                        """
                        UPDATE workflow_instances
                        SET status = 'completed', updated_at = now(), completed_at = now()
                        WHERE id = %s
                        """,
                        (workflow_id,),
                    )

                    # Write email_link_resolved audit event inside the same transaction
                    cur.execute(
                        """
                        INSERT INTO workflow_events
                            (tenant_id, workflow_instance_id, event_type,
                             actor_employee_id, actor_user_id, data)
                        VALUES (%s, %s, 'email_link_resolved', %s::uuid, %s, %s)
                        """,
                        (
                            tenant_id,
                            str(workflow_id),
                            resolver_id,
                            None,
                            json.dumps({"decision": decision, "correlation_token": correlation_token}),
                        ),
                    )

                    days_requested = None
                    employee_code = None

                    if leave_request_id:
                        # Fetch leave request details
                        cur.execute(
                            """
                            SELECT lr.days_requested, lr.leave_type_id, lr.employee_id,
                                   e.employee_code, lt.deducts_balance
                            FROM leave_requests lr
                            JOIN employees e ON e.id = lr.employee_id
                            JOIN leave_types lt ON lt.id = lr.leave_type_id
                            WHERE lr.id = %s
                            """,
                            (leave_request_id,),
                        )
                        lr = cur.fetchone()
                        if lr:
                            days_requested = _float(lr["days_requested"])
                            employee_code = lr["employee_code"]
                            leave_type_id = lr["leave_type_id"]
                            employee_id = lr["employee_id"]
                            deducts = lr["deducts_balance"]

                            # Update leave_request status (manager decision via email link)
                            new_lr_status = "manager_approved" if decision == "approved" else "manager_rejected"
                            cur.execute(
                                """
                                UPDATE leave_requests
                                SET status = %s, manager_id = COALESCE(manager_id, %s),
                                    manager_decision_at = now(), resolved_by = %s,
                                    resolved_at = now(), updated_at = now()
                                WHERE id = %s
                                """,
                                (new_lr_status, resolver_id, resolver_id, leave_request_id),
                            )

                            # Adjust leave_balances
                            if deducts and days_requested:
                                cur.execute(
                                    "SELECT start_date FROM leave_requests WHERE id = %s",
                                    (leave_request_id,),
                                )
                                sd_row = cur.fetchone()
                                balance_year = sd_row["start_date"].year if sd_row else None

                                if balance_year:
                                    if decision == "approved":
                                        cur.execute(
                                            """
                                            UPDATE leave_balances
                                            SET used_days = used_days + %s,
                                                pending_days = GREATEST(0, pending_days - %s),
                                                updated_at = now()
                                            WHERE tenant_id = %s AND employee_id = %s
                                              AND leave_type_id = %s AND year = %s
                                            """,
                                            (days_requested, days_requested,
                                             tenant_id, employee_id, leave_type_id, balance_year),
                                        )
                                    else:
                                        cur.execute(
                                            """
                                            UPDATE leave_balances
                                            SET pending_days = GREATEST(0, pending_days - %s),
                                                updated_at = now()
                                            WHERE tenant_id = %s AND employee_id = %s
                                              AND leave_type_id = %s AND year = %s
                                            """,
                                            (days_requested,
                                             tenant_id, employee_id, leave_type_id, balance_year),
                                        )

                    return {
                        "success": True,
                        "decision": decision,
                        "leave_request_id": str(leave_request_id) if leave_request_id else None,
                        "employee_code": employee_code,
                        "days_requested": days_requested,
                    }
        finally:
            self._release(conn)

    # ─── New read methods ──────────────────────────────────────────────────────

    def get_leave_type_by_code(self, tenant_id: str, code: str) -> dict | None:
        conn = self._conn()
        try:
            self._set_tenant(conn, tenant_id)
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    """
                    SELECT id, code, name_en, name_ar, requires_approval,
                           requires_documentation, deducts_balance, is_time_based,
                           requires_hr_review, max_days_per_year, max_consecutive_days,
                           max_times_in_career, service_min_days
                    FROM leave_types
                    WHERE tenant_id = %s AND code = %s AND is_active = TRUE
                    """,
                    (tenant_id, code),
                )
                row = cur.fetchone()
                if row is None:
                    return None
                r = dict(row)
                r["id"] = str(r["id"])
                return r
        finally:
            self._release(conn)

    def get_employee_age(self, tenant_id: str, employee_id: str) -> int | None:
        conn = self._conn()
        try:
            self._set_tenant(conn, tenant_id)
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT EXTRACT(YEAR FROM AGE(CURRENT_DATE, birth_date))::INTEGER
                    FROM employees
                    WHERE tenant_id = %s AND id = %s::uuid AND birth_date IS NOT NULL
                    """,
                    (tenant_id, employee_id),
                )
                row = cur.fetchone()
                return int(row[0]) if row else None
        finally:
            self._release(conn)

    def add_compensatory_day(
        self,
        tenant_id: str,
        employee_id: str,
        holiday_date: str,
        approved_by_employee_id: str,
    ) -> dict:
        conn = self._conn()
        try:
            self._set_tenant(conn, tenant_id)
            with conn:
                with conn.cursor(cursor_factory=RealDictCursor) as cur:
                    # Resolve annual leave_type id
                    cur.execute(
                        "SELECT id FROM leave_types WHERE tenant_id = %s AND code = 'annual' AND is_active = TRUE",
                        (tenant_id,),
                    )
                    lt_row = cur.fetchone()
                    if lt_row is None:
                        return {"success": False, "error": "Annual leave type not found"}
                    leave_type_id = lt_row["id"]

                    year = int(holiday_date[:4])
                    cur.execute(
                        """
                        UPDATE leave_balances
                        SET allocated_days = allocated_days + 1, updated_at = now()
                        WHERE tenant_id = %s
                          AND employee_id = %s::uuid
                          AND leave_type_id = %s
                          AND year = %s
                        RETURNING id, allocated_days
                        """,
                        (tenant_id, employee_id, leave_type_id, year),
                    )
                    row = cur.fetchone()
                    if row is None:
                        return {"success": False, "error": "Annual leave balance row not found for this employee"}
                    return {
                        "success": True,
                        "new_allocated_days": _float(row["allocated_days"]),
                        "leave_balance_id": str(row["id"]),
                    }
        finally:
            self._release(conn)

    def count_leave_type_usage(
        self, tenant_id: str, employee_id: str, leave_type_code: str
    ) -> int:
        conn = self._conn()
        try:
            self._set_tenant(conn, tenant_id)
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT COUNT(*)
                    FROM leave_requests lr
                    JOIN leave_types lt ON lt.id = lr.leave_type_id
                    WHERE lr.tenant_id = %s
                      AND lr.employee_id = %s::uuid
                      AND lt.code = %s
                      AND lr.status NOT IN (
                          'manager_rejected', 'hr_rejected', 'cancelled', 'withdrawn', 'cancellation_pending'
                      )
                    """,
                    (tenant_id, employee_id, leave_type_code),
                )
                row = cur.fetchone()
                return int(row[0]) if row else 0
        finally:
            self._release(conn)

    def get_leave_policy(self, tenant_id: str, leave_type_id: str) -> dict | None:
        conn = self._conn()
        try:
            self._set_tenant(conn, tenant_id)
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    """
                    SELECT probation_restriction_days, annual_allowance_days,
                           wfh_max_days_per_week, wfh_max_days_per_month,
                           max_consecutive_days, requires_medical_cert_after_days,
                           min_notice_days
                    FROM leave_policies
                    WHERE tenant_id = %s AND leave_type_id = %s
                    """,
                    (tenant_id, leave_type_id),
                )
                row = cur.fetchone()
                if row is None:
                    return None
                r = dict(row)
                for f in ("annual_allowance_days",):
                    r[f] = _float(r.get(f))
                return r
        finally:
            self._release(conn)

    def get_leave_request_by_id(self, tenant_id: str, request_id: str) -> dict | None:
        conn = self._conn()
        try:
            self._set_tenant(conn, tenant_id)
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    """
                    SELECT lr.id, lr.status, lr.days_requested, lr.duration_hours,
                           lr.start_date, lr.end_date, lr.start_datetime, lr.end_datetime,
                           lr.reason, lr.rejection_reason, lr.manager_comment,
                           lr.submitted_at, lr.updated_at,
                           lr.has_medical_certificate,
                           lr.workflow_instance_id,
                           e.employee_code, e.full_name AS employee_name, e.id AS employee_id,
                           e.department AS employee_department,
                           lt.code AS leave_type_code, lt.name_en AS leave_type_name,
                           lt.deducts_balance, lt.id AS leave_type_id,
                           mgr.employee_code AS manager_code, mgr.id AS manager_db_id
                    FROM leave_requests lr
                    JOIN employees e ON e.id = lr.employee_id
                    JOIN leave_types lt ON lt.id = lr.leave_type_id
                    LEFT JOIN employees mgr ON mgr.id = lr.manager_id
                    WHERE lr.tenant_id = %s AND lr.id = %s
                    """,
                    (tenant_id, request_id),
                )
                row = cur.fetchone()
                if row is None:
                    return None
                r = dict(row)
                r["id"] = str(r["id"])
                r["employee_id"] = str(r["employee_id"]) if r.get("employee_id") else None
                r["leave_type_id"] = str(r["leave_type_id"]) if r.get("leave_type_id") else None
                r["manager_db_id"] = str(r["manager_db_id"]) if r.get("manager_db_id") else None
                r["workflow_instance_id"] = str(r["workflow_instance_id"]) if r.get("workflow_instance_id") else None
                r["start_date"] = _isodate(r.get("start_date"))
                r["end_date"] = _isodate(r.get("end_date"))
                r["start_datetime"] = _isodate(r.get("start_datetime"))
                r["end_datetime"] = _isodate(r.get("end_datetime"))
                r["submitted_at"] = _isodate(r.get("submitted_at"))
                r["updated_at"] = _isodate(r.get("updated_at"))
                r["days_requested"] = _float(r.get("days_requested"))
                r["duration_hours"] = _float(r.get("duration_hours"))
                return r
        finally:
            self._release(conn)

    def get_leave_request_by_token(self, tenant_id: str, correlation_token: str) -> dict | None:
        conn = self._conn()
        try:
            self._set_tenant(conn, tenant_id)
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    """
                    SELECT wi.leave_request_id,
                           approver.employee_code AS approver_employee_code,
                           u.role                 AS approver_role
                    FROM pending_actions pa
                    JOIN workflow_instances wi ON wi.id = pa.workflow_instance_id
                    LEFT JOIN employees approver
                           ON approver.id = pa.assigned_to_employee_id
                    LEFT JOIN users u
                           ON u.employee_id = pa.assigned_to_employee_id
                          AND u.tenant_id = pa.tenant_id
                    WHERE pa.tenant_id = %s
                      AND pa.correlation_token = %s
                      AND pa.status = 'pending'
                    """,
                    (tenant_id, correlation_token),
                )
                row = cur.fetchone()
                if row is None:
                    return None
                approver_employee_code = row["approver_employee_code"]
                approver_role = row["approver_role"] or "hr_manager"
                leave_request_id = str(row["leave_request_id"])
        finally:
            self._release(conn)

        lr = self.get_leave_request_by_id(tenant_id, leave_request_id)
        if lr is None:
            return None
        lr["approver_employee_code"] = approver_employee_code
        lr["approver_role"] = approver_role
        return lr

    def get_leave_requests_for_employee(
        self,
        tenant_id: str,
        employee_id: str,
        status: str | None = None,
        limit: int = 10,
    ) -> list[dict]:
        conn = self._conn()
        try:
            self._set_tenant(conn, tenant_id)
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    """
                    SELECT lr.id, lr.status, lr.days_requested, lr.duration_hours,
                           lr.start_date, lr.end_date, lr.start_datetime, lr.end_datetime,
                           lr.reason, lr.rejection_reason, lr.manager_comment,
                           lr.submitted_at,
                           lt.code AS leave_type_code, lt.name_en AS leave_type_name,
                           mgr.full_name AS manager_name
                    FROM leave_requests lr
                    JOIN leave_types lt ON lt.id = lr.leave_type_id
                    LEFT JOIN employees mgr ON mgr.id = lr.manager_id
                    WHERE lr.tenant_id = %s
                      AND lr.employee_id = %s
                      AND (%s IS NULL OR lr.status = %s)
                    ORDER BY lr.submitted_at DESC
                    LIMIT %s
                    """,
                    (tenant_id, employee_id, status, status, limit),
                )
                rows = []
                for row in cur.fetchall():
                    r = dict(row)
                    r["id"] = str(r["id"])
                    r["start_date"] = _isodate(r.get("start_date"))
                    r["end_date"] = _isodate(r.get("end_date"))
                    r["start_datetime"] = _isodate(r.get("start_datetime"))
                    r["end_datetime"] = _isodate(r.get("end_datetime"))
                    r["submitted_at"] = _isodate(r.get("submitted_at"))
                    r["days_requested"] = _float(r.get("days_requested"))
                    r["duration_hours"] = _float(r.get("duration_hours"))
                    rows.append(r)
                return rows
        finally:
            self._release(conn)

    def get_pending_approvals_for_manager(
        self, tenant_id: str, manager_employee_id: str
    ) -> list[dict]:
        conn = self._conn()
        try:
            self._set_tenant(conn, tenant_id)
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    """
                    SELECT lr.id, lr.status, lr.days_requested, lr.duration_hours,
                           lr.start_date, lr.end_date, lr.start_datetime, lr.end_datetime,
                           lr.reason, lr.submitted_at,
                           e.employee_code, e.full_name AS employee_name,
                           lt.code AS leave_type_code, lt.name_en AS leave_type_name
                    FROM leave_requests lr
                    JOIN employees e ON e.id = lr.employee_id
                    JOIN leave_types lt ON lt.id = lr.leave_type_id
                    WHERE lr.tenant_id = %s
                      AND lr.manager_id = %s
                      AND lr.status = 'pending_approval'
                    ORDER BY lr.submitted_at ASC
                    """,
                    (tenant_id, manager_employee_id),
                )
                rows = []
                for row in cur.fetchall():
                    r = dict(row)
                    r["id"] = str(r["id"])
                    r["start_date"] = _isodate(r.get("start_date"))
                    r["end_date"] = _isodate(r.get("end_date"))
                    r["start_datetime"] = _isodate(r.get("start_datetime"))
                    r["end_datetime"] = _isodate(r.get("end_datetime"))
                    r["submitted_at"] = _isodate(r.get("submitted_at"))
                    r["days_requested"] = _float(r.get("days_requested"))
                    r["duration_hours"] = _float(r.get("duration_hours"))
                    rows.append(r)
                return rows
        finally:
            self._release(conn)

    def check_leave_overlap(
        self,
        tenant_id: str,
        employee_id: str,
        start_date: str,
        end_date: str,
        exclude_request_id: str | None = None,
    ) -> bool:
        conn = self._conn()
        try:
            self._set_tenant(conn, tenant_id)
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT 1 FROM leave_requests
                    WHERE tenant_id = %s
                      AND employee_id = %s
                      AND status IN ('pending_approval', 'manager_approved', 'hr_approved')
                      AND start_date IS NOT NULL
                      AND start_date <= %s::date
                      AND end_date >= %s::date
                      AND (%s IS NULL OR id != %s::uuid)
                    LIMIT 1
                    """,
                    (tenant_id, employee_id, end_date, start_date,
                     exclude_request_id, exclude_request_id),
                )
                return cur.fetchone() is not None
        finally:
            self._release(conn)

    def get_wfh_usage(
        self,
        tenant_id: str,
        employee_id: str,
        week_start: str,
        month: int,
        year: int,
    ) -> dict:
        conn = self._conn()
        try:
            self._set_tenant(conn, tenant_id)
            with conn.cursor() as cur:
                # Days this week (Mon–Sun window)
                cur.execute(
                    """
                    SELECT COALESCE(SUM(days_requested), 0)
                    FROM leave_requests lr
                    JOIN leave_types lt ON lt.id = lr.leave_type_id AND lt.code = 'wfh'
                    WHERE lr.tenant_id = %s
                      AND lr.employee_id = %s
                      AND lr.status IN ('pending_approval', 'manager_approved', 'hr_approved')
                      AND lr.start_date >= %s::date
                      AND lr.start_date <= (%s::date + INTERVAL '6 days')
                    """,
                    (tenant_id, employee_id, week_start, week_start),
                )
                days_this_week = float(cur.fetchone()[0] or 0)

                # Days this month
                cur.execute(
                    """
                    SELECT COALESCE(SUM(days_requested), 0)
                    FROM leave_requests lr
                    JOIN leave_types lt ON lt.id = lr.leave_type_id AND lt.code = 'wfh'
                    WHERE lr.tenant_id = %s
                      AND lr.employee_id = %s
                      AND lr.status IN ('pending_approval', 'manager_approved', 'hr_approved')
                      AND EXTRACT(MONTH FROM lr.start_date) = %s
                      AND EXTRACT(YEAR FROM lr.start_date) = %s
                    """,
                    (tenant_id, employee_id, month, year),
                )
                days_this_month = float(cur.fetchone()[0] or 0)

                return {"days_this_week": days_this_week, "days_this_month": days_this_month}
        finally:
            self._release(conn)

    # ─── New write methods ─────────────────────────────────────────────────────

    def update_leave_balance(
        self,
        tenant_id: str,
        employee_id: str,
        leave_type_id: str,
        year: int,
        delta_pending: float = 0.0,
        delta_used: float = 0.0,
    ) -> bool:
        conn = self._conn()
        try:
            self._set_tenant(conn, tenant_id)
            with conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        UPDATE leave_balances
                        SET pending_days = GREATEST(0, pending_days + %s),
                            used_days    = GREATEST(0, used_days + %s),
                            updated_at   = now()
                        WHERE tenant_id     = %s
                          AND employee_id   = %s
                          AND leave_type_id = %s
                          AND year          = %s
                        """,
                        (delta_pending, delta_used, tenant_id, employee_id, leave_type_id, year),
                    )
                    return cur.rowcount > 0
        finally:
            self._release(conn)

    def update_leave_request_status(
        self,
        tenant_id: str,
        request_id: str,
        new_status: str,
        metadata: dict,
    ) -> bool:
        conn = self._conn()
        try:
            self._set_tenant(conn, tenant_id)
            with conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        UPDATE leave_requests
                        SET status               = %s,
                            manager_comment      = COALESCE(%s, manager_comment),
                            manager_decision_at  = CASE WHEN %s IS NOT NULL
                                                        THEN now()
                                                        ELSE manager_decision_at END,
                            hr_comment           = COALESCE(%s, hr_comment),
                            hr_decision_at       = CASE WHEN %s IS NOT NULL
                                                        THEN now()
                                                        ELSE hr_decision_at END,
                            hr_reviewer_id       = COALESCE(%s::uuid, hr_reviewer_id),
                            resolved_by          = COALESCE(%s::uuid, resolved_by),
                            resolved_at          = CASE WHEN %s IS NOT NULL
                                                        THEN now()
                                                        ELSE resolved_at END,
                            rejection_reason     = COALESCE(%s, rejection_reason),
                            updated_at           = now()
                        WHERE tenant_id = %s AND id = %s
                        """,
                        (
                            new_status,
                            metadata.get("manager_comment"),
                            metadata.get("manager_comment"),
                            metadata.get("hr_comment"),
                            metadata.get("hr_comment"),
                            metadata.get("hr_reviewer_id"),
                            metadata.get("resolved_by_id"),
                            metadata.get("resolved_by_id"),
                            metadata.get("rejection_reason"),
                            tenant_id,
                            request_id,
                        ),
                    )
                    return cur.rowcount > 0
        finally:
            self._release(conn)

    # ─── Workflow events ───────────────────────────────────────────────────────

    def create_workflow_event(
        self,
        tenant_id: str,
        workflow_instance_id: str | None,
        event_type: str,
        actor_employee_id: str | None,
        actor_user_id: str | None,
        data: dict,
    ) -> dict:
        conn = self._conn()
        try:
            self._set_tenant(conn, tenant_id)
            with conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO workflow_events
                            (tenant_id, workflow_instance_id, event_type,
                             actor_employee_id, actor_user_id, data)
                        VALUES (%s, %s, %s, %s::uuid, %s, %s)
                        RETURNING id, event_type, created_at
                        """,
                        (
                            tenant_id,
                            workflow_instance_id,
                            event_type,
                            actor_employee_id,
                            actor_user_id,
                            json.dumps(data),
                        ),
                    )
                    row = cur.fetchone()
                    return {"id": str(row[0]), "event_type": row[1], "created_at": str(row[2])}
        finally:
            self._release(conn)

    def sync_workflow_decision(
        self,
        tenant_id: str,
        leave_request_id: str,
        decision: str,
        actor_employee_id: str | None,
        actor_user_id: str | None,
        resolution_note: str | None,
    ) -> bool:
        """Atomically close the pending_action + workflow_instance for a leave request
        that was approved/rejected via the tool path (not the email-link path).
        Returns True if an active pending_action was found and closed."""
        pa_status = "approved" if decision == "approved" else "rejected"
        event_type = "manager_approved" if decision == "approved" else "manager_rejected"

        conn = self._conn()
        try:
            self._set_tenant(conn, tenant_id)
            with conn:
                with conn.cursor() as cur:
                    # 1. Find the active pending_action linked to this leave request
                    cur.execute(
                        """
                        SELECT pa.id, pa.workflow_instance_id
                        FROM pending_actions pa
                        JOIN workflow_instances wi ON wi.id = pa.workflow_instance_id
                        WHERE wi.leave_request_id = %s::uuid
                          AND pa.status = 'pending'
                          AND pa.tenant_id = %s
                        LIMIT 1
                        """,
                        (leave_request_id, tenant_id),
                    )
                    row = cur.fetchone()
                    if not row:
                        return False
                    pending_action_id, workflow_instance_id = row

                    # 2. Mark pending_action resolved
                    cur.execute(
                        """
                        UPDATE pending_actions
                        SET status = %s,
                            resolved_at = now(),
                            resolved_by_employee_id = %s::uuid,
                            resolution_note = %s
                        WHERE id = %s AND tenant_id = %s
                        """,
                        (
                            pa_status,
                            actor_employee_id,
                            resolution_note,
                            pending_action_id,
                            tenant_id,
                        ),
                    )

                    # 3. Mark workflow_instance completed
                    cur.execute(
                        """
                        UPDATE workflow_instances
                        SET status = 'completed',
                            current_step = 'completed',
                            updated_at = now(),
                            completed_at = now()
                        WHERE id = %s AND tenant_id = %s
                        """,
                        (workflow_instance_id, tenant_id),
                    )

                    # 4. Write workflow_events row
                    cur.execute(
                        """
                        INSERT INTO workflow_events
                            (tenant_id, workflow_instance_id, event_type,
                             actor_employee_id, actor_user_id, data)
                        VALUES (%s, %s, %s, %s::uuid, %s, %s)
                        """,
                        (
                            tenant_id,
                            str(workflow_instance_id),
                            event_type,
                            actor_employee_id,
                            actor_user_id,
                            json.dumps({"note": resolution_note}),
                        ),
                    )
                    return True
        finally:
            self._release(conn)

    def get_tenant_settings(self, tenant_id: str) -> dict:
        conn = self._conn()
        try:
            self._set_tenant(conn, tenant_id)
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT settings FROM tenants WHERE id = %s",
                    (tenant_id,),
                )
                row = cur.fetchone()
                if not row:
                    return {}
                return row[0] if isinstance(row[0], dict) else {}
        finally:
            self._release(conn)

    def count_active_leaves_in_department(
        self,
        tenant_id: str,
        department: str,
        start_date: str,
        end_date: str,
        exclude_request_id: str | None = None,
    ) -> dict:
        conn = self._conn()
        try:
            self._set_tenant(conn, tenant_id)
            with conn.cursor() as cur:
                # Total headcount in department
                cur.execute(
                    "SELECT COUNT(*) FROM employees WHERE tenant_id = %s AND department = %s",
                    (tenant_id, department),
                )
                total = int(cur.fetchone()[0])

                # Active (approved) leaves overlapping the date range
                exclude_clause = "AND lr.id != %s::uuid" if exclude_request_id else ""
                params = [tenant_id, department, end_date, start_date]
                if exclude_request_id:
                    params.append(exclude_request_id)
                cur.execute(
                    f"""
                    SELECT COUNT(DISTINCT lr.employee_id)
                    FROM leave_requests lr
                    JOIN employees e ON e.id = lr.employee_id AND e.tenant_id = lr.tenant_id
                    WHERE lr.tenant_id = %s
                      AND e.department = %s
                      AND lr.status IN ('manager_approved', 'hr_approved')
                      AND lr.start_date <= %s
                      AND lr.end_date >= %s
                      {exclude_clause}
                    """,
                    params,
                )
                active = int(cur.fetchone()[0])
                return {"active_count": active, "total_employees": total}
        finally:
            self._release(conn)

    def record_appropriateness_decision(
        self,
        tenant_id: str,
        event_id: str,
        decision: str,
    ) -> None:
        conn = self._conn()
        try:
            self._set_tenant(conn, tenant_id)
            with conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        UPDATE workflow_events
                        SET data = data || jsonb_build_object('human_decision', %s)
                        WHERE id = %s::uuid AND tenant_id = %s
                        """,
                        (decision, event_id, tenant_id),
                    )
        finally:
            self._release(conn)

    # ─── Leave: cancellation methods ──────────────────────────────────────────

    def request_leave_cancellation(
        self,
        tenant_id: str,
        leave_request_id: str,
        requesting_employee_id: str,
        reason: str | None,
    ) -> dict:
        conn = self._conn()
        try:
            self._set_tenant(conn, tenant_id)
            with conn:
                with conn.cursor(cursor_factory=RealDictCursor) as cur:
                    cur.execute(
                        """
                        SELECT lr.id, lr.status, lr.days_requested,
                               lr.start_date, lr.end_date,
                               e.full_name AS employee_name,
                               lt.name_en AS leave_type_name,
                               lt.deducts_balance, lt.id AS leave_type_id,
                               lr.employee_id
                        FROM leave_requests lr
                        JOIN employees e ON e.id = lr.employee_id
                        JOIN leave_types lt ON lt.id = lr.leave_type_id
                        WHERE lr.tenant_id = %s AND lr.id = %s::uuid
                        FOR UPDATE
                        """,
                        (tenant_id, leave_request_id),
                    )
                    row = cur.fetchone()
                    if row is None:
                        return {"success": False, "error": "Leave request not found."}
                    if row["status"] not in ("manager_approved", "hr_approved"):
                        return {
                            "success": False,
                            "error": (
                                f"Cannot request cancellation — current status is '{row['status']}'. "
                                "Only manager_approved or hr_approved requests can be cancelled this way."
                            ),
                        }

                    cur.execute(
                        """
                        UPDATE leave_requests
                        SET status = 'cancellation_pending',
                            cancellation_requested_at = now(),
                            cancellation_requested_by_id = %s::uuid,
                            cancellation_reason = %s,
                            updated_at = now()
                        WHERE tenant_id = %s AND id = %s::uuid
                        """,
                        (requesting_employee_id, reason, tenant_id, leave_request_id),
                    )

                    return {
                        "success": True,
                        "leave_request_id": leave_request_id,
                        "employee_name": row["employee_name"],
                        "leave_type": row["leave_type_name"],
                        "start_date": _isodate(row["start_date"]),
                        "end_date": _isodate(row["end_date"]),
                        "days_requested": _float(row["days_requested"]),
                    }
        finally:
            self._release(conn)

    def approve_leave_cancellation(
        self,
        tenant_id: str,
        leave_request_id: str,
        decided_by_employee_id: str,
        consumed_days: float | None,
    ) -> dict:
        conn = self._conn()
        try:
            self._set_tenant(conn, tenant_id)
            with conn:
                with conn.cursor(cursor_factory=RealDictCursor) as cur:
                    cur.execute(
                        """
                        SELECT lr.id, lr.status, lr.days_requested,
                               lr.start_date, lr.end_date,
                               lr.employee_id, lr.leave_type_id,
                               e.full_name AS employee_name,
                               e.employee_code, e.email AS employee_email,
                               lt.name_en AS leave_type_name,
                               lt.deducts_balance
                        FROM leave_requests lr
                        JOIN employees e ON e.id = lr.employee_id
                        JOIN leave_types lt ON lt.id = lr.leave_type_id
                        WHERE lr.tenant_id = %s AND lr.id = %s::uuid
                        FOR UPDATE
                        """,
                        (tenant_id, leave_request_id),
                    )
                    row = cur.fetchone()
                    if row is None:
                        return {"success": False, "error": "Leave request not found."}
                    if row["status"] != "cancellation_pending":
                        return {
                            "success": False,
                            "error": f"Cannot approve cancellation — current status is '{row['status']}'.",
                        }

                    days_requested = _float(row["days_requested"]) or 0.0
                    today = date.today()
                    start = row["start_date"]
                    end = row["end_date"]

                    if consumed_days is not None:
                        days_to_restore = days_requested - float(consumed_days)
                    elif start is not None and start > today:
                        days_to_restore = days_requested
                    elif end is not None and end < today:
                        days_to_restore = 0.0
                    else:
                        days_to_restore = 0.0

                    days_to_restore = max(0.0, days_to_restore)

                    cur.execute(
                        """
                        UPDATE leave_requests
                        SET status = 'cancelled',
                            cancellation_decided_at = now(),
                            cancellation_decided_by_id = %s::uuid,
                            consumed_days = %s,
                            updated_at = now()
                        WHERE tenant_id = %s AND id = %s::uuid
                        """,
                        (
                            decided_by_employee_id,
                            float(consumed_days) if consumed_days is not None else None,
                            tenant_id,
                            leave_request_id,
                        ),
                    )

                    new_used_days = None
                    if row["deducts_balance"] and days_to_restore > 0 and start is not None:
                        year = start.year
                        cur.execute(
                            """
                            UPDATE leave_balances
                            SET used_days = GREATEST(0, used_days - %s),
                                updated_at = now()
                            WHERE tenant_id = %s
                              AND employee_id = %s::uuid
                              AND leave_type_id = %s::uuid
                              AND year = %s
                            RETURNING used_days
                            """,
                            (
                                days_to_restore,
                                tenant_id,
                                str(row["employee_id"]),
                                str(row["leave_type_id"]),
                                year,
                            ),
                        )
                        bal_row = cur.fetchone()
                        new_used_days = _float(bal_row["used_days"]) if bal_row else None

                    return {
                        "success": True,
                        "days_restored": days_to_restore,
                        "new_used_days": new_used_days,
                        "employee_name": row["employee_name"],
                        "employee_code": row["employee_code"],
                        "employee_email": row["employee_email"],
                        "start_date": str(row["start_date"]) if row["start_date"] else None,
                        "end_date": str(row["end_date"]) if row["end_date"] else None,
                        "leave_type": row["leave_type_name"],
                    }
        finally:
            self._release(conn)

    def get_pending_cancellations(self, tenant_id: str) -> list[dict]:
        conn = self._conn()
        try:
            self._set_tenant(conn, tenant_id)
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    """
                    SELECT lr.id,
                           e.full_name AS employee_name,
                           e.employee_code,
                           lt.name_en AS leave_type_name,
                           lr.start_date,
                           lr.end_date,
                           lr.days_requested,
                           lr.cancellation_reason,
                           lr.cancellation_requested_at
                    FROM leave_requests lr
                    JOIN employees e ON e.id = lr.employee_id
                    JOIN leave_types lt ON lt.id = lr.leave_type_id
                    WHERE lr.tenant_id = %s
                      AND lr.status = 'cancellation_pending'
                    ORDER BY lr.cancellation_requested_at ASC
                    """,
                    (tenant_id,),
                )
                rows = []
                for row in cur.fetchall():
                    r = dict(row)
                    r["id"] = str(r["id"])
                    r["start_date"] = _isodate(r.get("start_date"))
                    r["end_date"] = _isodate(r.get("end_date"))
                    r["cancellation_requested_at"] = _isodate(r.get("cancellation_requested_at"))
                    r["days_requested"] = _float(r.get("days_requested"))
                    rows.append(r)
                return rows
        finally:
            self._release(conn)

    def get_team_calendar(
        self,
        tenant_id: str,
        caller_role: str,
        caller_employee_id: str,
        year: int,
        month: int,
        department: str | None = None,
    ) -> dict:
        from calendar import monthrange
        from datetime import date as _date

        conn = self._conn()
        try:
            self._set_tenant(conn, tenant_id)
            with conn.cursor(cursor_factory=RealDictCursor) as cur:

                # A — Events scope: which employee IDs to show as clickable events
                if caller_role == "employee":
                    # Employee sees only their own events
                    events_scope_ids = [caller_employee_id] if caller_employee_id else []
                elif caller_role == "manager":
                    cur.execute(
                        "SELECT id FROM employees WHERE tenant_id = %s AND manager_id = %s::uuid",
                        (tenant_id, caller_employee_id),
                    )
                    events_scope_ids = [str(r["id"]) for r in cur.fetchall()]
                else:
                    # hr_staff / hr_manager / admin
                    if department:
                        cur.execute(
                            "SELECT id FROM employees WHERE tenant_id = %s AND department = %s",
                            (tenant_id, department),
                        )
                    else:
                        cur.execute(
                            "SELECT id FROM employees WHERE tenant_id = %s",
                            (tenant_id,),
                        )
                    events_scope_ids = [str(r["id"]) for r in cur.fetchall()]

                # B — Summary scope: all employees in tenant (or dept) for daily counts
                if department:
                    cur.execute(
                        "SELECT id FROM employees WHERE tenant_id = %s AND department = %s",
                        (tenant_id, department),
                    )
                else:
                    cur.execute(
                        "SELECT id FROM employees WHERE tenant_id = %s",
                        (tenant_id,),
                    )
                summary_scope_ids = [str(r["id"]) for r in cur.fetchall()]

                # C — Fetch leave events for the month
                _, days_in_month = monthrange(year, month)
                month_start = _date(year, month, 1)
                month_end = _date(year, month, days_in_month)

                ACTIVE_STATUSES = (
                    "pending_approval", "pending_top_of_hierarchy",
                    "manager_approved", "hr_approved", "cancellation_pending",
                )

                def _fetch_events(scope_ids: list[str]) -> list[dict]:
                    if not scope_ids:
                        return []
                    cur.execute(
                        """
                        SELECT lr.id,
                               lr.employee_id,
                               e.full_name,
                               e.employee_code,
                               e.department,
                               lt.code AS leave_type_code,
                               lt.name_en AS leave_type_label,
                               lr.start_date,
                               lr.end_date,
                               lr.status
                        FROM leave_requests lr
                        JOIN employees e  ON e.id = lr.employee_id  AND e.tenant_id = lr.tenant_id
                        JOIN leave_types lt ON lt.id = lr.leave_type_id AND lt.tenant_id = lr.tenant_id
                        WHERE lr.tenant_id = %s
                          AND lr.employee_id = ANY(%s::uuid[])
                          AND lr.status = ANY(%s)
                          AND lr.start_date <= %s
                          AND lr.end_date   >= %s
                        ORDER BY lr.start_date
                        """,
                        (tenant_id, scope_ids, list(ACTIVE_STATUSES), month_end, month_start),
                    )
                    return cur.fetchall()

                events_rows = _fetch_events(events_scope_ids)
                summary_rows = _fetch_events(summary_scope_ids)

                # D — Build events list with privacy rule
                caller_id_str = caller_employee_id or ""
                events = []
                for row in events_rows:
                    is_own = (str(row["employee_id"]) == caller_id_str)
                    show = (caller_role != "employee") or is_own
                    events.append({
                        "employee_name":    row["full_name"]        if show else None,
                        "employee_code":    row["employee_code"]    if show else None,
                        "leave_type_code":  row["leave_type_code"]  if show else None,
                        "leave_type_label": row["leave_type_label"] if show else None,
                        "start_date":       row["start_date"].isoformat(),
                        "end_date":         row["end_date"].isoformat(),
                        "status":           row["status"],
                        "department":       row["department"],
                        "is_own":           is_own,
                    })

                # E — Build daily_summary from summary-scope events
                total_employees = len(summary_scope_ids)
                daily_summary = {}
                for day in range(1, days_in_month + 1):
                    d = _date(year, month, day)
                    count = sum(
                        1 for row in summary_rows
                        if row["start_date"] <= d <= row["end_date"]
                    )
                    pct = (count / total_employees * 100) if total_employees > 0 else 0.0
                    daily_summary[d.isoformat()] = {
                        "on_leave_count": count,
                        "total_employees": total_employees,
                        "percentage": round(pct, 1),
                        "over_threshold": pct > 25.0,
                    }

                # F — Departments list
                cur.execute(
                    "SELECT DISTINCT department FROM employees "
                    "WHERE tenant_id = %s AND department IS NOT NULL ORDER BY department",
                    (tenant_id,),
                )
                departments = [r["department"] for r in cur.fetchall()]

                return {
                    "events": events,
                    "daily_summary": daily_summary,
                    "departments": departments,
                    "total_employees_in_scope": total_employees,
                }
        finally:
            self._release(conn)

    # ─── RAG / policy search ───────────────────────────────────────────────────

    def search_policy(
        self,
        tenant_id: str,
        query: str,
        caller_roles: list[str],
        limit: int = 5,
    ) -> list[dict]:
        # plainto_tsquery uses AND between all terms — a synonym not in the text
        # causes the whole query to miss. Instead, stem the query with to_tsvector
        # (which handles stop-word removal and stemming) and join the resulting
        # lexemes with OR (|) so any matching term is a hit.
        conn = self._conn()
        try:
            self._set_tenant(conn, tenant_id)
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    """
                    WITH q AS (
                        SELECT string_agg(lexeme, ' | ') AS or_query
                        FROM unnest(to_tsvector('english', %s))
                    )
                    SELECT document_id, chunk_index, content, source_file, sensitivity
                    FROM private_document_chunks, q
                    WHERE q.or_query IS NOT NULL
                      AND tenant_id = %s
                      AND classified_at IS NOT NULL
                      AND allowed_roles && %s::text[]
                      AND content_tsv @@ to_tsquery('english', q.or_query)
                    ORDER BY ts_rank(content_tsv, to_tsquery('english', q.or_query)) DESC
                    LIMIT %s
                    """,
                    (query, tenant_id, caller_roles, limit),
                )
                return [dict(r) for r in cur.fetchall()]
        finally:
            self._release(conn)
