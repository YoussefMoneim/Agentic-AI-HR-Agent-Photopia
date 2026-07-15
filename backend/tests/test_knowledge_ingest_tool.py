"""
Tests for tools/knowledge_ingest.py::IngestPolicyDocumentTool.

All tests mock KnowledgeBase.ingest() — no real Voyage AI call or live DB
required, matching the mock style of tests/test_email_agent.py.
"""
import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from unittest.mock import MagicMock

from knowledge.base import IngestResult
from tools.base import ToolContext
from tools.knowledge_ingest import IngestPolicyDocumentTool


def _ctx(role="hr_manager"):
    return ToolContext(
        tenant_id="tenant-uuid", user_id="test-user", role=role,
        employee_code="EMP002", display_name="Noura Al Rashidi",
    )


class TestIngestPolicyDocumentTool:

    def test_success_passes_access_level_all(self):
        mock_kb = MagicMock()
        mock_kb.ingest.return_value = IngestResult(
            document_id="employee_handbook", document_name="employee_handbook",
            chunks_created=4, chunks_replaced=0, success=True,
        )
        tool = IngestPolicyDocumentTool(mock_kb)
        result = tool.execute(
            {"content": "some handbook text", "document_name": "Employee Handbook.pdf"},
            _ctx(),
        )

        assert result.success is True
        assert result.data["chunks_created"] == 4
        mock_kb.ingest.assert_called_once()
        call_kwargs = mock_kb.ingest.call_args.kwargs
        assert call_kwargs["access_level"] == "all"
        assert call_kwargs["tenant_id"] == "tenant-uuid"
        assert call_kwargs["document_type"] == "policy"
        # document_name is canonicalized before reaching KnowledgeBase.ingest()
        assert call_kwargs["document_name"] == "employee_handbook"
        assert call_kwargs["ingested_by"] == "onboarding:test-user"

    def test_failure_surfaces_kb_error(self):
        mock_kb = MagicMock()
        mock_kb.ingest.return_value = IngestResult(
            document_id="", document_name="x", chunks_created=0, chunks_replaced=0,
            success=False, error="No extractable text.",
        )
        tool = IngestPolicyDocumentTool(mock_kb)
        result = tool.execute({"content": "x", "document_name": "x.pdf"}, _ctx())
        assert result.success is False
        assert result.error == "No extractable text."

    def test_rejects_empty_content(self):
        tool = IngestPolicyDocumentTool(MagicMock())
        result = tool.execute({"content": "  ", "document_name": "x.pdf"}, _ctx())
        assert result.success is False
        assert "content" in result.error.lower()

    def test_rejects_empty_document_name(self):
        tool = IngestPolicyDocumentTool(MagicMock())
        result = tool.execute({"content": "some text", "document_name": " "}, _ctx())
        assert result.success is False
        assert "document_name" in result.error.lower()

    def test_allowed_roles_exclude_employee(self):
        assert "employee" not in IngestPolicyDocumentTool.spec.allowed_roles
        assert "hr_manager" in IngestPolicyDocumentTool.spec.allowed_roles

    def test_registry_denies_employee_role(self):
        from tools.registry import ToolRegistry
        from audit.logger import AuditLogger

        mock_kb = MagicMock()
        registry = ToolRegistry([IngestPolicyDocumentTool(mock_kb)], MagicMock(spec=AuditLogger))
        result = registry.execute(
            "ingest_policy_document",
            {"content": "x", "document_name": "x.pdf"},
            _ctx(role="employee"),
        )
        assert result.success is False
        mock_kb.ingest.assert_not_called()
