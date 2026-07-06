from __future__ import annotations
from knowledge.base import KnowledgeBase
from tools.base import Tool, ToolContext, ToolResult, ToolSpec


class SearchPolicyTool(Tool):
    spec = ToolSpec(
        name="search_policy",
        description=(
            "Search the organization's HR policy knowledge base. "
            "Call this whenever an employee or manager asks about leave entitlements, rights, "
            "procedures, eligibility rules, or any HR policy topic. "
            "Returns relevant policy sections with source citations. "
            "Supports Arabic and English queries."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": (
                        "The policy question or topic to search for. "
                        "Be specific — 'annual leave notice period' is better than 'leave'. "
                        "Arabic queries are supported."
                    ),
                },
            },
            "required": ["query"],
        },
        allowed_roles=["employee", "hr_staff", "hr_manager", "admin"],
    )

    def __init__(self, knowledge_base: KnowledgeBase) -> None:
        self._kb = knowledge_base

    def execute(self, input: dict, ctx: ToolContext) -> ToolResult:
        query = input.get("query", "").strip()
        if not query:
            return ToolResult(success=False, error="query must not be empty")

        try:
            chunks = self._kb.search(
                query=query,
                tenant_id=ctx.tenant_id,
                user_role=ctx.role,
                top_k=5,
            )
        except Exception as e:
            return ToolResult(
                success=False,
                error=f"Knowledge base search failed: {e}",
            )

        if not chunks:
            return ToolResult(
                success=True,
                data={
                    "results": [],
                    "message": "No matching policy sections found.",
                },
                action_type="data_read",
                data_fields_accessed=["policy_corpus"],
            )

        return ToolResult(
            success=True,
            data={
                "results": [
                    {
                        "source": chunk.source_url or chunk.document_name,
                        "document": chunk.document_name,
                        "content": chunk.chunk_text,
                        "relevance": round(chunk.similarity_score, 3),
                    }
                    for chunk in chunks
                ],
                "instruction": "Cite the source document when referencing these policy sections.",
            },
            action_type="data_read",
            data_fields_accessed=["policy_corpus"],
        )
