# ADR-006: No manual document upload UI — SharePoint is the system of record
Date: 2026-07-09
Status: Accepted

## Decision
There is no manual "upload a policy document" UI feeding the knowledge base. SharePoint is the system of record for HR policy documents: the `sharepoint.py` connector's delta sync, plus the `ingest_policies.py` CLI script for one-time bootstrapping, are the only paths that write into `private_document_chunks`.

## Why
The master success criterion for this project is that a new client can upload documents to a system they already use, and employees are using a governed agent within days, with zero developer involvement in encoding rules or updating knowledge. That only holds if document ingestion is a connector-driven sync against a client's existing document system, not a bespoke upload UI a developer has to build and maintain per client. This also matches the connector-abstraction principle for the platform: source systems connect through a common interface, not one-off integrations.

## Consequences
Onboarding a new client's document store (SharePoint, or a different source in the future) means writing a new connector that implements sync/delta detection, not adding a generic upload form. The existing "demo document" upload/paste endpoints (`/api/documents/upload-demo`, `/api/documents/paste-demo`) are a separate feature — document-sensitivity scanning demos stored in `demo_documents` — and must never be confused with, or repurposed as, knowledge-base ingestion.
