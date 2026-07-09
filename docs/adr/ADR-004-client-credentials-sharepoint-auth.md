# ADR-004: Client credentials auth for SharePoint
Date: 2026-07-09
Status: Accepted

## Decision
The SharePoint connector authenticates using MSAL client credentials (Azure AD application permissions), not the interactive device code flow.

## Why
The device code flow's token cache is lost on every container rebuild, which silently breaks the connector on every redeploy — a real failure this project already hit. Client credentials authenticate with an application secret that survives restarts with no human re-authentication step, which is required for a background sync process that must keep running unattended. Relatedly, `offline_access` must never be passed explicitly in the MSAL scopes list — MSAL adds it automatically, and passing it explicitly causes a "reserved scope" error.

## Consequences
The connector requires a registered Azure AD application with the correct SharePoint application permissions granted by an admin, and its client secret must come from environment variables via `config.py` — never hardcoded, never pasted into chat or logs, and rotated immediately if it is ever exposed. This trades the simplicity of interactive login for an unattended, container-restart-safe connector, which is the correct tradeoff for a background sync process rather than a human-driven login flow.
