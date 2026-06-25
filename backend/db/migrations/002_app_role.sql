-- Migration 002: Create fotopia_app non-superuser role for application queries.
--
-- PostgreSQL exempts superusers from RLS policies, even with FORCE ROW LEVEL SECURITY.
-- The fotopia role (used for schema setup) is a superuser. Application code must
-- connect as fotopia_app (non-superuser) so RLS policies actually apply.
--
-- Apply to running container:
--   docker cp backend/db/migrations/002_app_role.sql fotopia-hr-agent-db-1:/tmp/
--   docker exec fotopia-hr-agent-db-1 psql -U fotopia -d fotopia_hr -f /tmp/002_app_role.sql
--
-- Idempotent: DO $$ IF NOT EXISTS $$ guard makes it safe to re-run.

DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'fotopia_app') THEN
        CREATE ROLE fotopia_app LOGIN PASSWORD 'fotopia_app';
    END IF;
END
$$;

-- Schema access
GRANT USAGE ON SCHEMA public TO fotopia_app;

-- Table-level DML
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO fotopia_app;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO fotopia_app;

-- Ensure future tables are also granted (for migrations)
ALTER DEFAULT PRIVILEGES IN SCHEMA public
    GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO fotopia_app;
ALTER DEFAULT PRIVILEGES IN SCHEMA public
    GRANT USAGE, SELECT ON SEQUENCES TO fotopia_app;
