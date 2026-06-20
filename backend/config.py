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

# Azure Communication Services — leave approval emails.
# Leave unset in dev to use mock (log-only) mode.
AZURE_COMMUNICATION_CONNECTION_STRING: str = os.getenv("AZURE_COMMUNICATION_CONNECTION_STRING", "")
AZURE_COMMUNICATION_SENDER_EMAIL: str = os.getenv("AZURE_COMMUNICATION_SENDER_EMAIL", "hr-agent@fotopia.ai")

# Base URL used in approval email links. Override in production.
API_BASE_URL: str = os.getenv("API_BASE_URL", "http://localhost:8000")
