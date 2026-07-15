from __future__ import annotations
from knowledge.base import KnowledgeBase
from knowledge.chunker import canonical_document_id
from tools.base import Tool, ToolContext, ToolResult, ToolSpec


class IngestPolicyDocumentTool(Tool):
    """Onboarding steps 4/5 — ingest an uploaded handbook/leave-policy document.

    Always ingests with access_level="all" so the same hr_manager who just
    uploaded the document can immediately query it back — see
    knowledge/pgvector_kb.py's _ACCESS_TO_ACL mapping."""

    spec = ToolSpec(
        name="ingest_policy_document",
        description=(
            "Ingest an uploaded policy document (employee handbook, leave "
            "policy, etc.) into the knowledge base during agent onboarding. "
            "The document becomes immediately searchable via search_policy."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "content": {"type": "string", "description": "Extracted document text"},
                "document_name": {"type": "string", "description": "Original filename or title"},
            },
            "required": ["content", "document_name"],
        },
        allowed_roles=["hr_manager", "admin"],
    )

    def __init__(self, knowledge_base: KnowledgeBase) -> None:
        self._kb = knowledge_base

    def execute(self, input: dict, ctx: ToolContext) -> ToolResult:
        content = (input.get("content") or "").strip()
        document_name = (input.get("document_name") or "").strip()

        if not content:
            return ToolResult(success=False, error="content must not be empty")
        if not document_name:
            return ToolResult(success=False, error="document_name must not be empty")

        result = self._kb.ingest(
            content=content,
            document_name=canonical_document_id(document_name),
            document_type="policy",
            tenant_id=ctx.tenant_id,
            access_level="all",
            ingested_by=f"onboarding:{ctx.user_id}",
            metadata={"original_filename": document_name},
        )

        if not result.success:
            return ToolResult(success=False, error=result.error or "Ingestion failed.")

        return ToolResult(
            success=True,
            data={
                "document_id": result.document_id,
                "chunks_created": result.chunks_created,
            },
            action_type="data_write",
        )
