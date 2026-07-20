"""
Tests for knowledge/chunker.py::canonical_document_id.

Ensures ingestion paths (local policies/, SharePoint) that pass different raw
strings as document_name normalize to the same document_id, so re-ingesting
the same document dedupes instead of accumulating chunks.
"""
from knowledge.chunker import canonical_document_id


def test_strips_path_and_extension():
    assert canonical_document_id("policies/public/03_leave_policy.md") == "03_leave_policy"


def test_normalizes_spaces_and_case():
    assert canonical_document_id("WIN Holding Leave Policy 2025") == "win_holding_leave_policy_2025"


def test_pdf_extension_stripped():
    assert canonical_document_id("leaves_policy_egypt_v2.pdf") == "leaves_policy_egypt_v2"


def test_local_and_sharepoint_names_for_same_document_converge():
    """The bug this fixes: same document, different raw names, must match."""
    local_stem = "win_holding_leave_policy_2025"
    sharepoint_filename = "WIN Holding Leave Policy 2025.docx"
    assert canonical_document_id(local_stem) == canonical_document_id(sharepoint_filename)


def test_collapses_repeated_separators():
    assert canonical_document_id("03 - Leave  Policy!!.md") == "03_leave_policy"
