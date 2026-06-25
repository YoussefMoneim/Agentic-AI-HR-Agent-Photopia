-- Migration 006: make workflow_events.workflow_instance_id nullable
-- Allows appropriateness_flag events from document tools that have no workflow instance.
-- Safe: existing rows are unaffected; NOT NULL is removed, FK reference is preserved.
ALTER TABLE workflow_events ALTER COLUMN workflow_instance_id DROP NOT NULL;
