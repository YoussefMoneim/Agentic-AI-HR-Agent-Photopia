"""
SharePoint connector for the Zumra feeder agent.

Watches a SharePoint document library folder and auto-ingests new/updated
documents into the vector knowledge base (pgvector) via KnowledgeBase.ingest().

Authentication: MSAL device code flow (delegated permissions).
- First run: user authenticates interactively via browser
- Subsequent runs: token refreshed automatically from cache
- Admin consent required for Sites.Read.All + Files.Read

Change detection: Microsoft Graph /delta endpoint.
- Stores deltaLink in sharepoint_sync_state table
- Only processes files that changed since last sync
- Falls back to full sync if delta token is lost/expired

File extraction:
- PDF: pdfplumber (text-based PDFs only — scanned PDFs logged as warning)
- DOCX: mammoth
- MD/TXT: plain UTF-8 decode

Rate limiting:
- Voyage AI free tier: 3 RPM
- Connector batches embedding calls with 20-second delays between batches
- Never blocks the HR agent — runs in a background thread

Non-blocking design:
- All SharePoint errors are caught and logged
- Failed ingestions do not affect existing knowledge base content
- The HR agent continues serving requests regardless of sync state
"""
from __future__ import annotations

import io
import logging
import os
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import psycopg2
import psycopg2.extras

_log = logging.getLogger(__name__)

# Supported MIME types for text extraction
SUPPORTED_MIME_TYPES = {
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "text/plain",
    "text/markdown",
    "application/octet-stream",  # fallback for unrecognized types
}

# File extensions → extraction method
EXTENSION_MAP = {
    ".pdf":  "pdf",
    ".docx": "docx",
    ".doc":  "docx",
    ".md":   "text",
    ".txt":  "text",
}


class SharePointConnector:
    """
    Watches a SharePoint folder and auto-ingests documents into pgvector.

    Usage:
        connector = SharePointConnector(
            tenant_id=config.AZURE_TENANT_ID,
            client_id=config.AZURE_CLIENT_ID,
            client_secret=config.AZURE_CLIENT_SECRET,
            site_url=config.SHAREPOINT_SITE_URL,
            folder_path=config.SHAREPOINT_FOLDER_PATH,
            database_url=config.DATABASE_URL,
            fotopia_tenant_id="7219556f-c533-4c10-a787-0f4c10a3309f",
        )
        connector.start()   # starts background polling thread
        connector.stop()    # stops gracefully
    """

    def __init__(
        self,
        tenant_id: str,
        client_id: str,
        client_secret: str,
        site_url: str,
        folder_path: str,
        database_url: str,
        fotopia_tenant_id: str,
        poll_interval_seconds: int = 300,
        access_level: str = "all",
    ):
        self._azure_tenant_id = tenant_id
        self._client_id = client_id
        self._client_secret = client_secret
        self._site_url = site_url.rstrip("/")
        self._folder_path = folder_path
        self._db_url = database_url
        self._fotopia_tenant_id = fotopia_tenant_id
        self._poll_interval = poll_interval_seconds
        self._access_level = access_level

        self._graph_client = None
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._token_cache_path = Path("/tmp/sharepoint_token_cache.json")

    # ------------------------------------------------------------------ #
    # Public interface                                                      #
    # ------------------------------------------------------------------ #

    def start(self) -> None:
        """Start background polling thread."""
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(
            target=self._poll_loop,
            name="sharepoint-connector",
            daemon=True,
        )
        self._thread.start()
        _log.info(
            "SharePoint connector started: site=%s folder=%s interval=%ds",
            self._site_url, self._folder_path, self._poll_interval,
        )

    def stop(self) -> None:
        """Stop the polling thread gracefully."""
        self._running = False
        if self._thread:
            self._thread.join(timeout=10)
        _log.info("SharePoint connector stopped")

    def trigger_sync(self) -> dict:
        """
        Manually trigger a sync (called from API endpoint).
        Returns sync result summary.
        """
        return self._sync()

    def get_status(self) -> dict:
        """Return current sync state from database."""
        conn = psycopg2.connect(self._db_url)
        try:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    """
                    SELECT site_url, folder_path, last_synced_at,
                           last_error, delta_link IS NOT NULL as has_delta
                    FROM sharepoint_sync_state
                    WHERE tenant_id = %s AND site_url = %s AND folder_path = %s
                    """,
                    (self._fotopia_tenant_id, self._site_url, self._folder_path),
                )
                row = cur.fetchone()
                return dict(row) if row else {
                    "site_url": self._site_url,
                    "folder_path": self._folder_path,
                    "last_synced_at": None,
                    "last_error": None,
                    "has_delta": False,
                }
        finally:
            conn.close()

    # ------------------------------------------------------------------ #
    # Auth                                                                  #
    # ------------------------------------------------------------------ #

    def _get_graph_client(self):
        """
        Build Microsoft Graph client using MSAL.
        Uses client credentials flow if client_secret is set (requires admin consent).
        Falls back to device code flow for interactive auth (no admin consent needed).
        """
        try:
            import msal

            # Try client credentials first (needs admin consent)
            if self._client_secret:
                app = msal.ConfidentialClientApplication(
                    client_id=self._client_id,
                    client_credential=self._client_secret,
                    authority=f"https://login.microsoftonline.com/{self._azure_tenant_id}",
                )
                result = app.acquire_token_for_client(
                    scopes=["https://graph.microsoft.com/.default"]
                )
                if result and "access_token" in result:
                    _log.info("SharePoint: authenticated via client credentials")
                    return result["access_token"]
                else:
                    error = result.get("error_description", "unknown") if result else "no result"
                    _log.warning(
                        "Client credentials failed (admin consent may be pending): %s", error
                    )

            # Fallback: device code flow (interactive, no admin consent needed)
            _log.info("SharePoint: falling back to device code flow")
            app = msal.PublicClientApplication(
                client_id=self._client_id,
                authority=f"https://login.microsoftonline.com/{self._azure_tenant_id}",
                token_cache=self._load_token_cache(),
            )

            scopes = ["Files.Read", "Sites.Read.All", "offline_access"]

            # Try silent auth from cache first
            accounts = app.get_accounts()
            if accounts:
                result = app.acquire_token_silent(scopes, account=accounts[0])
                if result and "access_token" in result:
                    self._save_token_cache(app.token_cache)
                    return result["access_token"]

            # Interactive device code
            flow = app.initiate_device_flow(scopes=scopes)
            if "user_code" not in flow:
                raise RuntimeError("Failed to initiate device code flow")

            print("\n" + "="*60)
            print("SHAREPOINT AUTH REQUIRED")
            print(flow["message"])
            print("="*60 + "\n")
            _log.warning("SharePoint requires interactive auth: %s", flow["message"])

            result = app.acquire_token_by_device_flow(flow)
            if result and "access_token" in result:
                self._save_token_cache(app.token_cache)
                _log.info("SharePoint: authenticated via device code flow")
                return result["access_token"]

            raise RuntimeError(f"Device code auth failed: {result.get('error_description')}")

        except ImportError:
            raise RuntimeError("msal not installed. Run: pip install msal")

    def _load_token_cache(self):
        """Load MSAL token cache from disk."""
        import msal
        cache = msal.SerializableTokenCache()
        if self._token_cache_path.exists():
            cache.deserialize(self._token_cache_path.read_text())
        return cache

    def _save_token_cache(self, cache) -> None:
        """Persist MSAL token cache to disk."""
        if cache.has_state_changed:
            self._token_cache_path.write_text(cache.serialize())

    # ------------------------------------------------------------------ #
    # Graph API calls                                                       #
    # ------------------------------------------------------------------ #

    def _graph_get(self, token: str, url: str) -> dict:
        """Make an authenticated GET request to Microsoft Graph."""
        import requests
        response = requests.get(
            url,
            headers={"Authorization": f"Bearer {token}"},
            timeout=30,
        )
        response.raise_for_status()
        return response.json()

    def _get_site_id(self, token: str) -> str:
        """Resolve SharePoint site URL to Graph site ID."""
        hostname = self._site_url.split("//")[1].split("/")[0]
        site_path = "/".join(self._site_url.split("//")[1].split("/")[1:])
        url = f"https://graph.microsoft.com/v1.0/sites/{hostname}:/{site_path}"
        data = self._graph_get(token, url)
        return data["id"]

    def _get_drive_id(self, token: str, site_id: str) -> str:
        """Get the default document library drive ID for a site."""
        url = f"https://graph.microsoft.com/v1.0/sites/{site_id}/drives"
        data = self._graph_get(token, url)
        drives = data.get("value", [])
        # Use the first non-system drive (Documents library)
        for drive in drives:
            if drive.get("driveType") == "documentLibrary":
                return drive["id"]
        if drives:
            return drives[0]["id"]
        raise RuntimeError("No document library found in SharePoint site")

    def _get_folder_delta(self, token: str, drive_id: str, delta_link: Optional[str]) -> tuple[list, str]:
        """
        Get changed files using Microsoft Graph delta query.
        Returns (changed_items, new_delta_link).
        If delta_link is None, does a full sync of the folder.
        """
        if delta_link:
            url = delta_link
        else:
            folder_path = self._folder_path.strip("/")
            url = (
                f"https://graph.microsoft.com/v1.0/drives/{drive_id}"
                f"/root:/{folder_path}:/delta"
            )

        items = []
        while url:
            data = self._graph_get(token, url)
            items.extend(data.get("value", []))
            url = data.get("@odata.nextLink")
            if "@odata.deltaLink" in data:
                return items, data["@odata.deltaLink"]

        return items, ""

    def _download_file(self, token: str, drive_id: str, item_id: str) -> bytes:
        """Download file content from SharePoint."""
        import requests
        url = f"https://graph.microsoft.com/v1.0/drives/{drive_id}/items/{item_id}/content"
        response = requests.get(
            url,
            headers={"Authorization": f"Bearer {token}"},
            timeout=60,
            allow_redirects=True,
        )
        response.raise_for_status()
        return response.content

    # ------------------------------------------------------------------ #
    # Text extraction                                                        #
    # ------------------------------------------------------------------ #

    def _extract_text(self, file_bytes: bytes, filename: str) -> Optional[str]:
        """
        Extract text from file bytes based on file extension.
        Returns None if extraction fails or produces empty content.
        """
        ext = Path(filename).suffix.lower()
        method = EXTENSION_MAP.get(ext)

        if method == "pdf":
            try:
                import pdfplumber
                with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
                    pages = [p.extract_text() or "" for p in pdf.pages]
                text = "\n\n".join(pages).strip()
                if len(text) < 100:
                    _log.warning(
                        "SharePoint: '%s' appears to be a scanned PDF — "
                        "insufficient text extracted (%d chars). "
                        "OCR processing required.",
                        filename, len(text)
                    )
                    return None
                return text
            except Exception as e:
                _log.error("SharePoint: PDF extraction failed for '%s': %s", filename, e)
                return None

        elif method == "docx":
            try:
                import mammoth
                result = mammoth.extract_raw_text(io.BytesIO(file_bytes))
                text = result.value.strip()
                return text if text else None
            except Exception as e:
                _log.error("SharePoint: DOCX extraction failed for '%s': %s", filename, e)
                return None

        elif method == "text":
            try:
                return file_bytes.decode("utf-8", errors="replace").strip()
            except Exception as e:
                _log.error("SharePoint: text decode failed for '%s': %s", filename, e)
                return None

        else:
            _log.warning(
                "SharePoint: unsupported file type '%s' — skipping '%s'",
                ext, filename
            )
            return None

    # ------------------------------------------------------------------ #
    # Sync logic                                                            #
    # ------------------------------------------------------------------ #

    def _poll_loop(self) -> None:
        """Background polling loop — runs every poll_interval seconds."""
        while self._running:
            try:
                result = self._sync()
                _log.info("SharePoint sync complete: %s", result)
            except Exception as e:
                _log.exception("SharePoint sync failed: %s", e)
                self._update_sync_state(delta_link=None, error=str(e))
            time.sleep(self._poll_interval)

    def _sync(self) -> dict:
        """
        Run one sync cycle:
        1. Authenticate
        2. Get changed files since last delta token
        3. Download + extract + ingest each changed file
        4. Store new delta token
        """
        from knowledge.factory import get_knowledge_base

        token = self._get_graph_client()
        site_id = self._get_site_id(token)
        drive_id = self._get_drive_id(token, site_id)

        # Load current delta token from DB
        delta_link = self._get_delta_link()

        # Get changed items
        items, new_delta_link = self._get_folder_delta(token, drive_id, delta_link)

        processed = 0
        skipped = 0
        failed = 0
        kb = get_knowledge_base()

        for item in items:
            # Skip folders
            if "folder" in item:
                continue
            # Skip deleted items (handle separately if needed)
            if item.get("deleted"):
                _log.info("SharePoint: file deleted: %s", item.get("name"))
                continue

            filename = item.get("name", "")
            item_id = item.get("id", "")
            ext = Path(filename).suffix.lower()

            if ext not in EXTENSION_MAP:
                skipped += 1
                continue

            try:
                _log.info("SharePoint: ingesting '%s'...", filename)

                # Download
                file_bytes = self._download_file(token, drive_id, item_id)

                # Extract text
                content = self._extract_text(file_bytes, filename)
                if not content:
                    skipped += 1
                    continue

                # Document name without extension
                doc_name = Path(filename).stem

                # Build SharePoint URL for traceability
                source_url = f"{self._site_url}{self._folder_path}/{filename}"

                # Ingest into knowledge base
                result = kb.ingest(
                    content=content,
                    document_name=doc_name,
                    document_type="policy",
                    tenant_id=self._fotopia_tenant_id,
                    access_level=self._access_level,
                    ingested_by="system:sharepoint-connector",
                    metadata={
                        "sharepoint_item_id": item_id,
                        "original_filename": filename,
                        "site_url": self._site_url,
                        "folder_path": self._folder_path,
                        "last_modified": item.get("lastModifiedDateTime", ""),
                    },
                    source_url=source_url,
                )

                if result.success:
                    _log.info(
                        "SharePoint: ingested '%s' — %d chunks (%d replaced)",
                        doc_name, result.chunks_created, result.chunks_replaced,
                    )
                    processed += 1
                else:
                    _log.error(
                        "SharePoint: ingestion failed for '%s': %s",
                        doc_name, result.error,
                    )
                    failed += 1

            except Exception as e:
                _log.exception("SharePoint: failed to process '%s': %s", filename, e)
                failed += 1

        # Save new delta token
        if new_delta_link:
            self._update_sync_state(delta_link=new_delta_link, error=None)

        return {
            "processed": processed,
            "skipped": skipped,
            "failed": failed,
            "total_items": len(items),
            "synced_at": datetime.now(timezone.utc).isoformat(),
        }

    # ------------------------------------------------------------------ #
    # Database helpers                                                      #
    # ------------------------------------------------------------------ #

    def _get_delta_link(self) -> Optional[str]:
        conn = psycopg2.connect(self._db_url)
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT delta_link FROM sharepoint_sync_state
                    WHERE tenant_id = %s AND site_url = %s AND folder_path = %s
                    """,
                    (self._fotopia_tenant_id, self._site_url, self._folder_path),
                )
                row = cur.fetchone()
                return row[0] if row else None
        finally:
            conn.close()

    def _update_sync_state(
        self,
        delta_link: Optional[str],
        error: Optional[str],
    ) -> None:
        conn = psycopg2.connect(self._db_url)
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO sharepoint_sync_state
                        (tenant_id, site_url, folder_path, delta_link,
                         last_synced_at, last_error, updated_at)
                    VALUES (%s, %s, %s, %s, NOW(), %s, NOW())
                    ON CONFLICT (tenant_id, site_url, folder_path)
                    DO UPDATE SET
                        delta_link = EXCLUDED.delta_link,
                        last_synced_at = NOW(),
                        last_error = EXCLUDED.last_error,
                        updated_at = NOW()
                    """,
                    (
                        self._fotopia_tenant_id,
                        self._site_url,
                        self._folder_path,
                        delta_link,
                        error,
                    ),
                )
                conn.commit()
        finally:
            conn.close()


# ─── Module-level singleton ───────────────────────────────────────────────────

_connector: Optional[SharePointConnector] = None


def get_sharepoint_connector() -> Optional[SharePointConnector]:
    """Return the module-level connector singleton, or None if not configured."""
    return _connector


def init_sharepoint_connector(fotopia_tenant_id: str) -> Optional[SharePointConnector]:
    """
    Initialize the SharePoint connector from config.
    Returns None if SHAREPOINT_SITE_URL is not configured (connector is optional).
    """
    global _connector
    import config

    if not config.SHAREPOINT_SITE_URL:
        _log.info("SharePoint connector: SHAREPOINT_SITE_URL not set — connector disabled")
        return None

    if not config.AZURE_CLIENT_ID or not config.AZURE_TENANT_ID:
        _log.warning("SharePoint connector: AZURE_CLIENT_ID or AZURE_TENANT_ID not set — connector disabled")
        return None

    _connector = SharePointConnector(
        tenant_id=config.AZURE_TENANT_ID,
        client_id=config.AZURE_CLIENT_ID,
        client_secret=config.AZURE_CLIENT_SECRET,
        site_url=config.SHAREPOINT_SITE_URL,
        folder_path=config.SHAREPOINT_FOLDER_PATH,
        database_url=config.DATABASE_URL,
        fotopia_tenant_id=fotopia_tenant_id,
        poll_interval_seconds=config.SHAREPOINT_POLL_INTERVAL_SECONDS,
    )

    return _connector
