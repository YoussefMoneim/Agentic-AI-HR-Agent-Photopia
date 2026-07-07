"""
Validate SharePoint connector configuration and connectivity.
Run this to check everything is wired correctly before a real SharePoint URL is configured.

Usage:
    docker exec fotopia-hr-agent-backend-1 python /app/scripts/test_sharepoint_connector.py
"""
import sys
sys.path.insert(0, '/app')

import config
import psycopg2

def check_config():
    print("\n=== SharePoint Connector Configuration ===")
    checks = [
        ("AZURE_CLIENT_ID", config.AZURE_CLIENT_ID),
        ("AZURE_TENANT_ID", config.AZURE_TENANT_ID),
        ("AZURE_CLIENT_SECRET", "***set***" if config.AZURE_CLIENT_SECRET else ""),
        ("SHAREPOINT_SITE_URL", config.SHAREPOINT_SITE_URL),
        ("SHAREPOINT_FOLDER_PATH", config.SHAREPOINT_FOLDER_PATH),
        ("SHAREPOINT_POLL_INTERVAL_SECONDS", str(config.SHAREPOINT_POLL_INTERVAL_SECONDS)),
    ]
    all_ok = True
    for key, value in checks:
        status = "✓" if value else "✗ NOT SET"
        print(f"  {status}  {key}: {value if value else 'empty'}")
        if not value and key not in ("SHAREPOINT_SITE_URL",):
            all_ok = False
    return all_ok

def check_migration():
    print("\n=== Database Migration (020) ===")
    conn = psycopg2.connect(config.DATABASE_URL)
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT column_name FROM information_schema.columns
                WHERE table_name = 'sharepoint_sync_state'
                ORDER BY ordinal_position
            """)
            columns = [r[0] for r in cur.fetchall()]
            if columns:
                print(f"  ✓ Table exists: {', '.join(columns)}")
            else:
                print("  ✗ Table missing — run migration 020")
                return False

            cur.execute("""
                SELECT relrowsecurity, relforcerowsecurity
                FROM pg_class WHERE relname = 'sharepoint_sync_state'
            """)
            row = cur.fetchone()
            if row and row[0] and row[1]:
                print("  ✓ RLS enabled and forced")
            else:
                print("  ✗ RLS not properly configured")
                return False
        return True
    finally:
        conn.close()

def check_msal():
    print("\n=== MSAL Auth Library ===")
    try:
        import msal
        print(f"  ✓ msal {msal.__version__} installed")
        return True
    except ImportError:
        print("  ✗ msal not installed")
        return False

def check_connector_import():
    print("\n=== Connector Module ===")
    try:
        from connectors.sharepoint import init_sharepoint_connector, SharePointConnector
        print("  ✓ connectors.sharepoint imports cleanly")
        connector = init_sharepoint_connector("7219556f-c533-4c10-a787-0f4c10a3309f")
        if connector is None:
            print("  ✓ init_sharepoint_connector returns None (SHAREPOINT_SITE_URL not set — expected)")
        else:
            print("  ✓ Connector initialized")
        return True
    except Exception as e:
        print(f"  ✗ Import failed: {e}")
        return False

def check_api_endpoints():
    print("\n=== API Endpoints ===")
    try:
        import requests
        token_r = requests.post("http://localhost:8000/auth/login", json={
            "email": "noura.rashidi@fotopiatech.com",
            "password": "demo123"
        }, timeout=5)
        if token_r.status_code != 200:
            print(f"  ✗ Login failed: {token_r.status_code}")
            return False
        token = token_r.json().get("token") or token_r.json().get("access_token")
        headers = {"Authorization": f"Bearer {token}"}

        for path, method in [
            ("/api/knowledge/sharepoint/status", "GET"),
            ("/api/knowledge/documents", "GET"),
        ]:
            r = requests.request(method, f"http://localhost:8000{path}", headers=headers, timeout=5)
            status = "✓" if r.status_code in (200, 503) else "✗"
            print(f"  {status} {method} {path} → {r.status_code}")
        return True
    except Exception as e:
        print(f"  ✗ API check failed: {e}")
        return False

if __name__ == "__main__":
    results = [
        check_config(),
        check_migration(),
        check_msal(),
        check_connector_import(),
        check_api_endpoints(),
    ]
    print("\n" + "="*50)
    if all(results):
        print("✓ SharePoint connector ready")
        print("  Next: set SHAREPOINT_SITE_URL in .env to activate")
    else:
        print("✗ Some checks failed — review output above")
    sys.exit(0 if all(results) else 1)
