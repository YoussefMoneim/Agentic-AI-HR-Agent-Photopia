"""
Tests for PolicyEngine dynamic constraint evaluation.

Uses unittest.mock to avoid live API calls — no Voyage AI, no LLM calls.
Tests verify the decision logic and fallback behavior, not the LLM/KB integration.
Integration validation is done manually via test_knowledge_base.py.

All existing Hajj tests in test_win_policy.py must still pass (they test
the hardcoded fallback path via the registry, which triggers when PolicyEngine
returns certain=False — mocked here to do exactly that).
"""
import json
from unittest.mock import MagicMock, patch

import pytest

from workflow.policy_engine import (
    CONFIDENCE_THRESHOLD,
    PolicyChunk,
    PolicyDecision,
    PolicyEngine,
)


@pytest.fixture
def engine(tenant_id: str) -> PolicyEngine:
    """PolicyEngine instance for fotopia tenant, employee role."""
    return PolicyEngine(tenant_id=tenant_id, user_role="employee")


def _mock_chunk(content: str, score: float = 0.85) -> PolicyChunk:
    return PolicyChunk(
        document_id="03_leave_policy_v2_WIN",
        chunk_index=17,
        content=content,
        similarity_score=score,
        source_url="sharepoint/HR Policies/03_leave_policy_v2_WIN.md",
    )


# ── Failure / fallback paths ──────────────────────────────────────────────────

def test_certain_false_when_no_chunks(engine: PolicyEngine) -> None:
    """Engine returns certain=False when knowledge base returns no relevant chunks."""
    with patch.object(engine, "_retrieve_policy", return_value=[]):
        decision = engine.evaluate_hajj_eligibility(
            service_days=2000,
            previous_hajj_leaves=0,
        )
    assert decision.certain is False
    assert decision.eligible is False


def test_certain_false_when_chunks_below_threshold(engine: PolicyEngine) -> None:
    """Low-confidence chunks (below CONFIDENCE_THRESHOLD) are filtered out → certain=False."""
    low_score_chunks = [_mock_chunk("Some policy text.", score=CONFIDENCE_THRESHOLD - 0.01)]
    with patch.object(engine, "_retrieve_policy", return_value=low_score_chunks):
        decision = engine.evaluate_hajj_eligibility(
            service_days=2000,
            previous_hajj_leaves=0,
        )
    assert decision.certain is False


def test_certain_false_when_llm_fails(engine: PolicyEngine) -> None:
    """Engine returns certain=False when LLM call raises an exception."""
    chunks = [_mock_chunk("Hajj leave requires 5 years of service.")]
    with patch.object(engine, "_retrieve_policy", return_value=chunks):
        with patch.object(engine, "_reason_about_policy", return_value=None):
            decision = engine.evaluate_hajj_eligibility(
                service_days=2000,
                previous_hajj_leaves=0,
            )
    assert decision.certain is False


def test_certain_false_when_llm_returns_uncertain(engine: PolicyEngine) -> None:
    """When LLM says uncertain=true, decision is certain=False (not ineligible)."""
    chunks = [_mock_chunk("Leave policy section 3.")]
    uncertain_response = {
        "uncertain": True,
        "reason": "Policy documents do not clearly address this question",
    }
    with patch.object(engine, "_retrieve_policy", return_value=chunks):
        with patch.object(engine, "_reason_about_policy", return_value=uncertain_response):
            decision = engine.evaluate_hajj_eligibility(
                service_days=2000,
                previous_hajj_leaves=0,
            )
    assert decision.certain is False
    assert decision.eligible is False  # uncertain ≠ eligible


# ── Happy paths ───────────────────────────────────────────────────────────────

def test_eligible_with_sufficient_service(engine: PolicyEngine) -> None:
    """Employee with >5 years service and 0 prior Hajj leaves → eligible=True."""
    chunks = [_mock_chunk(
        "The employee must have been working for the company for more than "
        "5 consecutive years on a full-time basis. Entitlement: once in career."
    )]
    llm_response = {
        "uncertain": False,
        "eligible": True,
        "reason": "Employee has 2000 days (≈5.5 years) service, meeting the 5-year requirement.",
        "policy_citation": (
            "The employee must have been working for the company for more than "
            "5 consecutive years on a full-time basis."
        ),
        "policy_source": "03_leave_policy_v2_WIN, chunk 17",
        "conditions": ["Must not have previously taken Hajj leave"],
        "requires_documentation": True,
    }
    with patch.object(engine, "_retrieve_policy", return_value=chunks):
        with patch.object(engine, "_reason_about_policy", return_value=llm_response):
            decision = engine.evaluate_hajj_eligibility(
                service_days=2000,
                previous_hajj_leaves=0,
            )
    assert decision.certain is True
    assert decision.eligible is True
    assert decision.confidence_score == 0.85
    assert "5 consecutive years" in decision.policy_citation
    assert decision.policy_source == "03_leave_policy_v2_WIN, chunk 17"


def test_ineligible_insufficient_service(engine: PolicyEngine) -> None:
    """Employee with <5 years service → eligible=False with policy citation."""
    chunks = [_mock_chunk(
        "Service requirement: more than 5 consecutive years on a full-time basis."
    )]
    llm_response = {
        "uncertain": False,
        "eligible": False,
        "reason": "Employee has 1200 days (≈3.3 years) service, below the 5-year minimum.",
        "policy_citation": "more than 5 consecutive years on a full-time basis",
        "policy_source": "03_leave_policy_v2_WIN, chunk 17",
        "conditions": [],
        "requires_documentation": False,
    }
    with patch.object(engine, "_retrieve_policy", return_value=chunks):
        with patch.object(engine, "_reason_about_policy", return_value=llm_response):
            decision = engine.evaluate_hajj_eligibility(
                service_days=1200,
                previous_hajj_leaves=0,
            )
    assert decision.certain is True
    assert decision.eligible is False
    assert "5-year minimum" in decision.reason


def test_ineligible_already_used_career_cap(engine: PolicyEngine) -> None:
    """Employee who already took Hajj leave once → eligible=False."""
    chunks = [_mock_chunk("Hajj leave is granted once in the total period of work.")]
    llm_response = {
        "uncertain": False,
        "eligible": False,
        "reason": "Employee has already taken Hajj leave 1 time, which is the career maximum.",
        "policy_citation": "once in the total period of work",
        "policy_source": "03_leave_policy_v2_WIN, chunk 17",
        "conditions": [],
        "requires_documentation": False,
    }
    with patch.object(engine, "_retrieve_policy", return_value=chunks):
        with patch.object(engine, "_reason_about_policy", return_value=llm_response):
            decision = engine.evaluate_hajj_eligibility(
                service_days=2500,
                previous_hajj_leaves=1,
            )
    assert decision.certain is True
    assert decision.eligible is False
    assert "once" in decision.policy_citation


# ── JSON parsing edge cases ───────────────────────────────────────────────────

def test_json_parse_failure_returns_certain_false(engine: PolicyEngine) -> None:
    """If LLM returns malformed JSON, engine returns certain=False gracefully."""
    chunks = [_mock_chunk("Hajj leave policy text.")]
    with patch.object(engine, "_retrieve_policy", return_value=chunks):
        with patch.object(engine, "_get_llm") as mock_get_llm:
            mock_provider = MagicMock()
            mock_provider.classify.return_value = "This is not JSON at all"
            mock_get_llm.return_value = mock_provider
            decision = engine.evaluate_hajj_eligibility(
                service_days=2000,
                previous_hajj_leaves=0,
            )
    assert decision.certain is False


def test_json_with_markdown_fence_parsed_correctly(engine: PolicyEngine) -> None:
    """If LLM wraps JSON in markdown fences, engine strips them and parses correctly."""
    chunks = [_mock_chunk("Hajj requires 5 years service.")]
    json_response = {
        "uncertain": False,
        "eligible": True,
        "reason": "Meets 5-year requirement.",
        "policy_citation": "Hajj requires 5 years service.",
        "policy_source": "03_leave_policy_v2_WIN, chunk 17",
        "conditions": [],
        "requires_documentation": True,
    }
    fenced = f"```json\n{json.dumps(json_response)}\n```"

    with patch.object(engine, "_retrieve_policy", return_value=chunks):
        with patch.object(engine, "_get_llm") as mock_get_llm:
            mock_provider = MagicMock()
            mock_provider.classify.return_value = fenced
            mock_get_llm.return_value = mock_provider
            decision = engine.evaluate_hajj_eligibility(
                service_days=2000,
                previous_hajj_leaves=0,
            )
    assert decision.certain is True
    assert decision.eligible is True
