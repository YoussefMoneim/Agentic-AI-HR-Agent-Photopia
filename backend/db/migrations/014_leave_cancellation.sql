-- Migration 014: Approved leave cancellation workflow
-- Policy (P-01): HR processes cancellations directly — no manager re-approval.
-- Policy (P-02): Partial restore supported — consumed_days tracks days already taken.
-- Policy (P-04): Full cancellation only. Employee resubmits for days actually needed.

-- ─── 1. Add cancellation_pending to the status CHECK ─────────────────────────

ALTER TABLE leave_requests DROP CONSTRAINT IF EXISTS leave_requests_status_check;
ALTER TABLE leave_requests ADD CONSTRAINT leave_requests_status_check
    CHECK (status IN (
        'pending_approval',
        'pending_top_of_hierarchy',
        'manager_approved', 'manager_rejected',
        'hr_approved', 'hr_rejected',
        'cancellation_pending',
        'cancelled', 'withdrawn', 'completed'
    ));

-- ─── 2. Cancellation tracking columns ────────────────────────────────────────

ALTER TABLE leave_requests
    ADD COLUMN IF NOT EXISTS cancellation_requested_at    TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS cancellation_reason          TEXT,
    ADD COLUMN IF NOT EXISTS cancellation_requested_by_id UUID REFERENCES employees(id),
    ADD COLUMN IF NOT EXISTS cancellation_decided_at      TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS cancellation_decided_by_id   UUID REFERENCES employees(id),
    ADD COLUMN IF NOT EXISTS cancellation_reject_reason   TEXT,
    ADD COLUMN IF NOT EXISTS consumed_days                NUMERIC(5,1);
    -- consumed_days: HR fills this when approving cancellation of an in-progress leave.
    -- days_to_restore = days_requested - consumed_days.

-- ─── 3. Index for HR cancellation inbox ──────────────────────────────────────

CREATE INDEX IF NOT EXISTS idx_leave_requests_cancellation_pending
    ON leave_requests(tenant_id, cancellation_requested_at)
    WHERE status = 'cancellation_pending';
