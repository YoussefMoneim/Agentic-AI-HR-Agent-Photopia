import json
import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

ANTHROPIC_API_KEY: str = os.environ["ANTHROPIC_API_KEY"]   # raises KeyError at startup if missing — intentional
XAI_API_KEY: str = os.getenv("XAI_API_KEY", "")            # only needed when LLM_PROVIDER=grok
LLM_PROVIDER: str = os.getenv("LLM_PROVIDER", "claude")
LLM_MODEL: str = os.getenv("LLM_MODEL", "claude-sonnet-4-5")

DATA_SOURCE: str = os.getenv("DATA_SOURCE", "mock")
DATABASE_URL: str = os.environ["DATABASE_URL"]

BASE_DIR = Path(__file__).parent
DOCUMENTS_DIR = Path(os.getenv("DOCUMENTS_DIR", str(BASE_DIR / "documents")))
TEMPLATES_DIR = Path(os.getenv("TEMPLATES_DIR", str(BASE_DIR / "templates")))
TENANT_CONFIG_DIR = Path(os.getenv("TENANT_CONFIG_DIR", str(BASE_DIR / "tenant_config")))

DOCUMENTS_DIR.mkdir(parents=True, exist_ok=True)

# Phase 1: single hard-coded tenant. Phase 2: resolve from JWT / subdomain.
TENANT_SLUG: str = os.getenv("TENANT_SLUG", "fotopia")

# Company name, address, signatory — loaded once and passed into every PDF builder.
_tenant_config_path = TENANT_CONFIG_DIR / f"{TENANT_SLUG}.json"
with open(_tenant_config_path) as _f:
    TENANT_CONFIG: dict = json.load(_f)

# Phase 1 demo identity switch. Set DEMO_ROLE=employee to test leave submission as EMP001 (Saif).
# Phase 2 replaces this entirely with JWT decoding in build_context().
DEMO_ROLE: str = os.getenv("DEMO_ROLE", "hr_manager")  # "employee" | "hr_manager"

# JWT — used for real authentication (Phase 2). Change JWT_SECRET in production.
JWT_SECRET: str = os.getenv("JWT_SECRET", "dev-secret-change-before-production")
# Defaults OFF. Only enable in local/dev — never staging or prod.
DEBUG_ALLOW_DEMO_ROLE: bool = os.getenv("DEBUG_ALLOW_DEMO_ROLE", "false").lower() == "true"
APP_ENV: str = os.getenv("APP_ENV", "")  # "local" | "dev" | "staging" | "prod"

if DEBUG_ALLOW_DEMO_ROLE and APP_ENV not in ("local", "dev"):
    raise RuntimeError(
        "SECURITY: DEBUG_ALLOW_DEMO_ROLE=True is only permitted when APP_ENV is 'local' or 'dev'. "
        "Set APP_ENV=local in your .env for local development, "
        "or set DEBUG_ALLOW_DEMO_ROLE=False."
    )

# Azure Communication Services — leave approval emails.
# Leave unset in dev to use mock (log-only) mode.
AZURE_COMMUNICATION_CONNECTION_STRING: str = os.getenv("AZURE_COMMUNICATION_CONNECTION_STRING", "")
AZURE_COMMUNICATION_SENDER_EMAIL: str = os.getenv("AZURE_COMMUNICATION_SENDER_EMAIL", "hr-agent@fotopia.ai")

# Base URL used in approval email links. Override in production.
API_BASE_URL: str = os.getenv("API_BASE_URL", "http://localhost:8000")

# ── SMTP (send path, fallback from ACS) ──────────────────────────────────────
# Leave all four unset to remain in mock (log-only) mode.
SMTP_HOST: str = os.getenv("SMTP_HOST", "")
SMTP_PORT: int = int(os.getenv("SMTP_PORT", "587"))
SMTP_USERNAME: str = os.getenv("SMTP_USERNAME", "")
SMTP_PASSWORD: str = os.getenv("SMTP_PASSWORD", "")
SMTP_USE_STARTTLS: bool = os.getenv("SMTP_USE_STARTTLS", "true").lower() == "true"
SMTP_FROM_ADDRESS: str = os.getenv("SMTP_FROM_ADDRESS", "")

# ── IMAP (receive path) ───────────────────────────────────────────────────────
# Set EMAIL_LISTENER_ENABLED=true AND provide IMAP credentials to activate.
EMAIL_LISTENER_ENABLED: bool = os.getenv("EMAIL_LISTENER_ENABLED", "false").lower() == "true"
IMAP_HOST: str = os.getenv("IMAP_HOST", "")
IMAP_PORT: int = int(os.getenv("IMAP_PORT", "993"))
IMAP_USERNAME: str = os.getenv("IMAP_USERNAME", "")
IMAP_PASSWORD: str = os.getenv("IMAP_PASSWORD", "")
EMAIL_LISTENER_POLL_INTERVAL_SECONDS: int = int(
    os.getenv("EMAIL_LISTENER_POLL_INTERVAL_SECONDS", "60")
)

# Domain used in outgoing Message-ID header: <{pending_action_uuid}@EMAIL_MESSAGE_ID_DOMAIN>
EMAIL_MESSAGE_ID_DOMAIN: str = os.getenv("EMAIL_MESSAGE_ID_DOMAIN", "hr.fotopia.com")
