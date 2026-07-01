#!/usr/bin/env bash
# reset_demo_environment.sh — Full demo environment rebuild.
#
# Tears down Docker volumes, starts fresh, resyncs Odoo employees,
# reseeds Odoo allocations, and reseeds demo documents.
#
# Run from the repo root:
#   bash backend/scripts/reset_demo_environment.sh
#
# NOTE: This restores the database to the base seed.sql state.
# Any live DB customizations (e.g. FT-2024-099, FT-2022-010 email change)
# will be lost and must be re-applied manually or added to seed.sql.
# For a quick pre-demo soft reset (no volume teardown), use demo_reset.py instead:
#   docker exec fotopia-hr-agent-backend-1 python /app/scripts/demo_reset.py

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
cd "$REPO_ROOT"

echo ""
echo "╔══════════════════════════════════════════════════╗"
echo "║        Fotopia HR — Full Demo Reset              ║"
echo "╚══════════════════════════════════════════════════╝"
echo ""

# ── Step 1: Tear down volumes and restart ──────────────────────────────────────
echo "=== Step 1/5: Tear down Docker volumes and restart ==="
docker compose down -v
docker compose up -d
echo "  Containers started. Waiting for backend to be healthy..."

# Wait up to 60s for the backend health endpoint to respond
ready=0
for i in $(seq 1 20); do
    if docker exec fotopia-hr-agent-backend-1 \
        python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')" \
        2>/dev/null; then
        echo "  ✓ Backend ready (attempt $i)"
        ready=1
        break
    fi
    echo "  Attempt $i/20 — waiting 3s..."
    sleep 3
done

if [ "$ready" -eq 0 ]; then
    echo "  ✗ Backend did not become healthy in 60s — aborting"
    exit 1
fi

# ── Step 2: Clear Odoo leave/allocation records and reseed allocations ─────────
echo ""
echo "=== Step 2/5: Clear Odoo demo data and reseed allocations ==="
docker exec fotopia-hr-agent-backend-1 python /app/scripts/clear_odoo_demo_data.py

# ── Step 3: Sync employees to Odoo ────────────────────────────────────────────
echo "=== Step 3/5: Sync employees to Odoo ==="
docker exec fotopia-hr-agent-backend-1 python /app/scripts/sync_employees_to_odoo.py

# ── Step 4: Clear email rate limit (idempotent) ───────────────────────────────
echo ""
echo "=== Step 4/5: Clear email rate limit ==="
docker exec fotopia-hr-agent-backend-1 python -c "
import os, sys
sys.path.insert(0, '/app')
import psycopg2, config
conn = psycopg2.connect(config.DATABASE_URL)
conn.autocommit = True
with conn.cursor() as cur:
    cur.execute('DELETE FROM email_agent_rate_limit')
    print(f'  Cleared email_agent_rate_limit ({cur.rowcount} rows)')
conn.close()
"

# ── Step 5: Seed demo documents ───────────────────────────────────────────────
echo ""
echo "=== Step 5/5: Seed demo documents ==="
docker exec fotopia-hr-agent-backend-1 python /app/scripts/seed_demo_documents.py

echo ""
echo "╔══════════════════════════════════════════════════╗"
echo "║  Done — demo environment is ready               ║"
echo "╚══════════════════════════════════════════════════╝"
echo ""
echo "Quick verification:"
echo "  curl localhost:8000/health"
echo "  docker exec fotopia-hr-agent-db-1 psql -U fotopia -d fotopia_hr \\"
echo "    -c \"SELECT COUNT(*) AS employees FROM employees;\""
echo ""
echo "If you applied live DB customizations (FT-2024-099, FT-2022-010 email),"
echo "re-apply them now or add them to backend/db/seed.sql."
