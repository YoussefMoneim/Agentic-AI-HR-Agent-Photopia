"""
PolicyEngine — dynamic constraint evaluation from the vector knowledge base.

ARCHITECTURE BOUNDARY (non-negotiable, enforced here and in callers):
  LLM reasons about WHETHER something is allowed (reads policy documents)
  Python enforces WHAT happens numerically (balance deductions, Odoo writes)
  Numbers from LLM output are NEVER used for enforcement decisions
  Irreversible actions never trigger on uncertain decisions

FAILURE BEHAVIOR (fail closed — never fail open):
  Policy retrieval fails     → PolicyDecision(certain=False)
  LLM call fails             → PolicyDecision(certain=False)
  Score below threshold      → PolicyDecision(certain=False)
  JSON parse fails           → PolicyDecision(certain=False)
  JSON parses but wrong shape → PolicyDecision(certain=False)
  LLM returns uncertain=true → PolicyDecision(certain=False)
  certain=False ALWAYS means caller falls back to hardcoded constraints.
  uncertain is NOT the same as ineligible.

  Note on the "wrong shape" case: LLMProvider.classify() has a default
  implementation (llm/base.py) that returns a fixed JSON string built for
  the document-sensitivity classifier feature, for providers that don't
  override it (only ClaudeProvider does today). That string parses as
  valid JSON but has neither "uncertain" nor "eligible" in the shape this
  engine expects — without a shape check it would be silently treated as
  a confident decision. _reason_about_policy() checks for the "uncertain"
  key before trusting the parse.

LLM ACCESS:
  Uses llm.factory.get_llm() and provider.classify() — never imports
  anthropic directly. Matches Rule 1 (only llm/claude.py imports anthropic).

AUDIT TRAIL:
  Every PolicyDecision includes policy_source (document + chunk).
  Callers must surface policy_citation in rejection reasons so employees
  can read the exact policy text that blocked their request.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Optional

_log = logging.getLogger(__name__)

# Minimum cosine similarity to trust a retrieved chunk.
# Below threshold → uncertain, fall back to hardcoded.
CONFIDENCE_THRESHOLD = 0.40

# Chunks to retrieve per policy question.
TOP_K = 3

# claude-haiku model string — matches ClaudeProvider.classify() usage elsewhere
POLICY_MODEL = "claude-haiku-4-5-20251001"


@dataclass
class PolicyChunk:
    """A retrieved policy chunk with source and confidence."""
    document_id: str
    chunk_index: int
    content: str
    similarity_score: float
    source_url: str


@dataclass
class PolicyDecision:
    """
    Result of dynamic policy evaluation.

    certain=False → caller MUST fall back to hardcoded constraints.
    certain=True  → LLM produced a grounded decision from policy documents.

    Never treat certain=False as a rejection. It means "we don't know
    from documents — use the database rules."
    """
    certain: bool
    eligible: bool = False
    reason: str = ""
    policy_citation: str = ""
    policy_source: str = ""
    conditions: list[str] = field(default_factory=list)
    requires_documentation: bool = False
    confidence_score: float = 0.0
    raw_chunks: list[PolicyChunk] = field(default_factory=list)


class PolicyEngine:
    """
    Evaluates leave eligibility dynamically from the vector knowledge base.

    Instantiate per-request with tenant_id and user_role.
    Call evaluate_*() methods for specific leave types.
    Each method returns PolicyDecision — check .certain before using .eligible.
    """

    def __init__(self, tenant_id: str, user_role: str = "employee"):
        self._tenant_id = tenant_id
        self._user_role = user_role
        self._kb = None
        self._llm = None

    def _get_kb(self):
        if self._kb is None:
            from knowledge.factory import get_knowledge_base
            self._kb = get_knowledge_base()
        return self._kb

    def _get_llm(self):
        if self._llm is None:
            from llm.factory import get_llm
            self._llm = get_llm()
        return self._llm

    def _retrieve_policy(self, query: str) -> list[PolicyChunk]:
        """
        Retrieve relevant policy chunks. Returns [] on any failure.
        Filters to chunks at or above CONFIDENCE_THRESHOLD.
        """
        try:
            kb = self._get_kb()
            chunks = kb.search(
                query=query,
                tenant_id=self._tenant_id,
                user_role=self._user_role,
                top_k=TOP_K,
            )
            result = [
                PolicyChunk(
                    document_id=c.document_id,
                    chunk_index=c.chunk_index,
                    content=c.chunk_text,
                    similarity_score=c.similarity_score,
                    source_url=c.source_url or c.document_name,
                )
                for c in chunks
                if c.similarity_score >= CONFIDENCE_THRESHOLD
            ]
            _log.debug(
                "PolicyEngine: retrieved %d chunks above threshold for query: %s",
                len(result), query[:60]
            )
            return result
        except Exception as e:
            _log.error("PolicyEngine: knowledge base retrieval failed: %s", e)
            return []

    def _reason_about_policy(
        self,
        chunks: list[PolicyChunk],
        question: str,
        context: dict,
    ) -> Optional[dict]:
        """
        Use LLM to reason about policy chunks and return structured decision.
        Returns None on any failure — caller treats None as certain=False.

        Uses provider.classify() which routes through llm/claude.py —
        never touches anthropic SDK directly.
        """
        if not chunks:
            return None

        policy_text = "\n\n---\n\n".join([
            f"[Source: {c.document_id}, chunk {c.chunk_index}]\n{c.content}"
            for c in chunks
        ])

        context_str = "\n".join(
            f"- {k}: {v}" for k, v in context.items()
        )

        system_prompt = """You are an HR policy compliance engine for an enterprise system.
Your decisions directly affect employees. Be precise, fair, and grounded ONLY in the policy text provided.

STRICT RULES:
1. You may ONLY cite text that appears in the provided policy documents
2. If the policy documents do not clearly address the question, return {"uncertain": true}
3. Never invent rules. Never assume. Only apply what is written in the documents.
4. Return ONLY valid JSON — no markdown, no explanation, no code blocks.

RESPONSE FORMAT (eligible):
{"uncertain": false, "eligible": true, "reason": "...", "policy_citation": "exact text from document", "policy_source": "document_id, chunk N", "conditions": ["..."], "requires_documentation": true/false}

RESPONSE FORMAT (ineligible):
{"uncertain": false, "eligible": false, "reason": "...", "policy_citation": "exact text from document", "policy_source": "document_id, chunk N", "conditions": [], "requires_documentation": false}

RESPONSE FORMAT (policy unclear):
{"uncertain": true, "reason": "Policy documents do not clearly address this question"}"""

        user_text = f"""POLICY DOCUMENTS:
{policy_text}

QUESTION: {question}

EMPLOYEE CONTEXT:
{context_str}

Respond with ONLY a JSON object."""

        raw = None
        try:
            provider = self._get_llm()
            raw = provider.classify(system_prompt, user_text)
            # Strip any accidental markdown fences
            text = raw.strip()
            if text.startswith("```"):
                lines = text.split("\n")
                text = "\n".join(
                    line for line in lines
                    if not line.startswith("```")
                ).strip()
            parsed = json.loads(text)
            # Shape check: LLMProvider.classify()'s default fallback (for
            # providers that don't override it) returns valid-but-unrelated
            # JSON (document-sensitivity classifier shape). Without this
            # check that would be silently treated as a confident decision.
            if not isinstance(parsed, dict) or "uncertain" not in parsed:
                _log.error(
                    "PolicyEngine: LLM response parsed but missing expected "
                    "'uncertain' key — treating as failure: %.200s", raw
                )
                return None
            return parsed
        except json.JSONDecodeError as e:
            _log.error(
                "PolicyEngine: LLM returned non-JSON response: %s — raw: %.200s",
                e, raw if raw is not None else "unavailable"
            )
            return None
        except Exception as e:
            _log.error("PolicyEngine: LLM reasoning failed: %s", e)
            return None

    def evaluate_hajj_eligibility(
        self,
        service_days: int,
        previous_hajj_leaves: int,
    ) -> PolicyDecision:
        """
        Dynamically evaluate Hajj leave eligibility from policy documents.

        Args:
            service_days: calendar days of employment (today - hire_date).days
            previous_hajj_leaves: count of approved Hajj leave requests on record

        Returns PolicyDecision with certain=False if retrieval or reasoning fails.
        Caller MUST fall back to hardcoded checks #6 and #7 when certain=False.
        """
        query = (
            "Hajj leave eligibility years service requirement "
            "pilgrimage entitlement once career frequency"
        )
        chunks = self._retrieve_policy(query)

        if not chunks:
            _log.warning(
                "PolicyEngine: no Hajj policy chunks above threshold %.2f "
                "for tenant %s — hardcoded fallback",
                CONFIDENCE_THRESHOLD, self._tenant_id,
            )
            return PolicyDecision(certain=False)

        years_approx = service_days / 365.25
        context = {
            "leave_type": "Hajj Leave",
            "employee_service_days": service_days,
            "employee_service_years_approximate": f"{years_approx:.1f}",
            "previous_hajj_leaves_on_record": previous_hajj_leaves,
        }

        question = (
            f"Is an employee with {service_days} days of service "
            f"(approximately {years_approx:.1f} years) who has previously "
            f"taken Hajj leave {previous_hajj_leaves} time(s) eligible "
            f"to take Hajj leave?"
        )

        result = self._reason_about_policy(chunks, question, context)

        if result is None:
            return PolicyDecision(certain=False)

        if result.get("uncertain", False):
            _log.info(
                "PolicyEngine: LLM returned uncertain for Hajj, tenant %s — "
                "hardcoded fallback. Reason: %s",
                self._tenant_id, result.get("reason", "")
            )
            return PolicyDecision(
                certain=False,
                reason=result.get("reason", ""),
            )

        top_score = max(c.similarity_score for c in chunks)

        decision = PolicyDecision(
            certain=True,
            eligible=result.get("eligible", False),
            reason=result.get("reason", ""),
            policy_citation=result.get("policy_citation", ""),
            policy_source=result.get("policy_source", ""),
            conditions=result.get("conditions", []),
            requires_documentation=result.get("requires_documentation", False),
            confidence_score=top_score,
            raw_chunks=chunks,
        )

        _log.info(
            "PolicyEngine: Hajj decision tenant=%s eligible=%s "
            "score=%.3f source=%s",
            self._tenant_id, decision.eligible,
            decision.confidence_score, decision.policy_source,
        )
        return decision
