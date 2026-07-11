# ADR-005: LLM decides IF, Python decides WHAT
Date: 2026-07-09
Status: Accepted

## Decision
Claude (the LLM) is only ever used to decide whether and which tool to call in response to a user's request. Every calculation, business rule, and access-control decision inside that tool is deterministic Python — the LLM never performs math, never invents document content, and never makes an authorization decision itself.

## Why
A wrong number on a legal document (salary certificate, end-of-service gratuity) is a lawsuit, so salary and other math is never done by the LLM — deterministic Python only. Access control follows the same logic ("policy before prompt"): the `ToolRegistry` filters the tool list by role before the LLM ever sees it, and re-checks role at execution time, so access control lives in tools and the database, never in the system prompt where an LLM could be talked around it.

## Consequences
Document-generation tools use hardcoded, DB-driven templates so the LLM cannot invent content or produce inconsistent output between runs, and calculations like end-of-service gratuity run through pure Python so the same inputs always produce the same, auditable result. Every tool call is written to `audit_log` regardless of outcome, which only remains meaningful because the decision logic that produced that outcome is deterministic code the team can inspect and test — not a black-box model judgment.
