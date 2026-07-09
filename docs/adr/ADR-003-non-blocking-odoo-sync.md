# ADR-003: Non-blocking Odoo sync
Date: 2026-07-09
Status: Accepted

## Decision
Odoo sync runs only after a leave approval or cancellation has already been committed in our own database, and is wrapped so that any failure is logged and swallowed rather than surfaced to the caller. A leave approval is never made to wait on, or fail because of, an Odoo response.

## Why
Odoo failures must never block leave approvals — if Odoo is unavailable, the correct behavior is to log the failure and let HR reconcile manually, not to hold up or roll back a decision that a manager has already made. Odoo is a downstream system of record for attendance/HRIS, not the authority over whether a leave request is approved; that decision is owned entirely by the manager and the constraint engine, both of which operate inside our own Postgres and don't need Odoo to be reachable.

## Consequences
HR must periodically reconcile Odoo against the internal leave register, since a silent sync failure can leave Odoo out of date until someone notices (the leave register Excel export exists partly to support this reconciliation). Any future integration with an external system of record should follow this same non-blocking pattern rather than introduce a hard runtime dependency on that system's availability.
