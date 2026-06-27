from data.base import DataSource
from tools.base import Tool, ToolContext, ToolResult, ToolSpec


class SearchPolicyTool(Tool):
    spec = ToolSpec(
        name="search_policy",
        description=(
            "Full-text search over the HR policy corpus. "
            "Call this whenever an employee or manager asks about leave entitlements, rights, "
            "procedures, or any HR policy topic. Returns matching policy sections with source citations."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "The policy question or keywords to search for.",
                },
            },
            "required": ["query"],
        },
        allowed_roles=["employee", "hr_staff", "hr_manager", "admin"],
    )

    def __init__(self, data_source: DataSource) -> None:
        self._ds = data_source

    def execute(self, input: dict, ctx: ToolContext) -> ToolResult:
        query = input.get("query", "").strip()
        if not query:
            return ToolResult(success=False, error="query must not be empty")

        results = self._ds.search_policy(
            tenant_id=ctx.tenant_id,
            query=query,
            caller_roles=[ctx.role],
            limit=5,
        )

        if not results:
            return ToolResult(
                success=True,
                data={"results": [], "message": "No matching policy sections found."},
                action_type="data_read",
                data_fields_accessed=["policy_corpus"],
            )

        formatted = [
            {
                "source": r["source_file"],
                "document": r["document_id"],
                "content": r["content"],
            }
            for r in results
        ]
        return ToolResult(
            success=True,
            data={
                "results": formatted,
                "instruction": "Cite the source document when referencing these policy sections.",
            },
            action_type="data_read",
            data_fields_accessed=["policy_corpus"],
        )
