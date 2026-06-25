-- Migration 007: add pending_top_of_hierarchy to leave_requests.status CHECK constraint
-- When an employee has no manager (top of hierarchy), their request is flagged for
-- board/delegate review instead of being routed to a manager for approval.
ALTER TABLE leave_requests DROP CONSTRAINT IF EXISTS leave_requests_status_check;
ALTER TABLE leave_requests ADD CONSTRAINT leave_requests_status_check
    CHECK (status IN (
        'pending_approval',
        'pending_top_of_hierarchy',
        'manager_approved', 'manager_rejected',
        'hr_approved', 'hr_rejected',
        'cancelled', 'withdrawn', 'completed'
    ));
