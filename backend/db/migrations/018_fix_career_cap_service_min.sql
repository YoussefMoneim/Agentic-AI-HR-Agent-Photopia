-- Migration 018: Fix missing service_min_days / max_times_in_career values
--
-- Bug: seed.sql creates marriage/hajj/umrah/maternity/paternity leave_types
-- rows WITHOUT service_min_days/max_times_in_career (columns didn't exist yet
-- when those INSERTs were first written). Migration 010's corrective
-- `INSERT ... ON CONFLICT (tenant_id, code) DO NOTHING` then silently no-ops
-- on every environment, because seed.sql already created the conflicting row —
-- so the WIN Holding service-minimum and career-usage-cap rules for these five
-- leave types were never actually enforced. seed.sql is fixed going forward;
-- this migration corrects any database that was already bootstrapped.

UPDATE leave_types lt
SET max_times_in_career = v.max_times_in_career,
    service_min_days = v.service_min_days
FROM tenants t,
     (VALUES
         ('marriage',  1, 365),
         ('hajj',      1, 1825),
         ('umrah',     1, 365),
         ('maternity', 3, 365),
         ('paternity', 3, 0)
     ) AS v(code, max_times_in_career, service_min_days)
WHERE lt.tenant_id = t.id
  AND t.slug = 'fotopia'
  AND lt.code = v.code
  AND (lt.max_times_in_career IS DISTINCT FROM v.max_times_in_career
       OR lt.service_min_days IS DISTINCT FROM v.service_min_days);
