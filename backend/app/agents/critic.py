"""
Critic & Verifier Agent.

This node acts as a gate before the patch reaches the human reviewer.
It performs deterministic checks first (syntax validation via AST) and only
invokes the LLM for the semantic review. This two-phase approach catches the
easy failures cheaply before spending LLM tokens on a syntactically broken patch.
"""

from __future__ import annotations

import json

import structlog
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_ollama import ChatOllama

from app.core.config import get_settings
from app.schemas.audit import (
    AgentNode,
    AuditState,
    AuditStatus,
    CriticOutput,
    CriticVerdict,
)
from app.tools.code_analysis import validate_python_syntax

log = structlog.get_logger(__name__)

_SYSTEM_PROMPT = """\
You are a code review specialist. You will receive an original vulnerable snippet
and a proposed security patch. Your job is to verify:

1. Does the patch actually fix the stated vulnerability?
2. Does it introduce new vulnerabilities or regressions?
3. Does it preserve the original behaviour for non-malicious inputs?
4. Are there unintended side-effects?

Respond ONLY with valid JSON. No prose.
"""


def _build_critic_prompt(state: AuditState) -> str:
    assert state.patcher_output is not None
    assert state.scanner_output is not None

    finding = next(
        (f for f in state.scanner_output.findings if f.id == state.patcher_output.finding_id),
        None,
    )
    finding_desc = finding.description if finding else "unknown"

    return f"""
VULNERABILITY BEING FIXED:
  ID: {state.patcher_output.finding_id}
  Description: {finding_desc}

RATIONALE PROVIDED BY PATCHER:
  {state.patcher_output.rationale}

ORIGINAL CODE:
```
{state.patcher_output.diff.original_snippet}
```

PATCHED CODE:
```
{state.patcher_output.diff.patched_snippet}
```

UNIFIED DIFF:
```diff
{state.patcher_output.diff.unified_diff}
```

Evaluate the patch and return:
{{
  "verdict": "approved|rejected",
  "feedback": "<specific, actionable feedback – what is wrong or confirm it's correct>",
  "syntax_valid": true,
  "potential_side_effects": ["<list of concerns, or empty array>"]
}}
"""


def run_critic_node(state: AuditState) -> AuditState:
    """
    LangGraph node: Critic & Verifier.

    Deterministic syntax check runs unconditionally. If syntax is invalid we
    short-circuit and reject without spending LLM tokens. Only syntactically
    valid patches proceed to LLM review.
    """
    settings = get_settings()
    logger = log.bind(thread_id=state.thread_id, node="critic")
    logger.info("Critic node started")

    if state.patcher_output is None:
        raise RuntimeError("Critic called without patcher_output in state")

    patched_code = state.patcher_output.diff.patched_snippet

    # Phase 1: cheap deterministic check – declare here so mypy sees one unified type across both branches
    critic_output: CriticOutput | None = None
    syntax_valid, syntax_error = validate_python_syntax(patched_code)
    if not syntax_valid:
        logger.warning("Patch failed syntax check, rejecting immediately", error=syntax_error)
        critic_output = CriticOutput(
            verdict=CriticVerdict.REJECTED,
            feedback=f"Patch has a syntax error and cannot be applied: {syntax_error}",
            syntax_valid=False,
            potential_side_effects=[],
        )
        return _build_state_after_critic(state, critic_output, logger)

    # Phase 2: LLM semantic review
    llm = ChatOllama(
        base_url=settings.ollama_base_url,
        model=settings.ollama_model,
        temperature=settings.ollama_temperature,
        timeout=settings.llm_timeout_seconds,
        format="json",
    )

    prompt = _build_critic_prompt(state)
    messages = [SystemMessage(content=_SYSTEM_PROMPT), HumanMessage(content=prompt)]

    for attempt in range(1, 3):
        try:
            response = llm.invoke(messages)
            raw = response.content
            if isinstance(raw, list):
                raw = " ".join(str(b) for b in raw)
            data = json.loads(raw)
            data["syntax_valid"] = True  # We already verified this above
            critic_output = CriticOutput.model_validate(data)
            logger.info("Critic LLM call succeeded", verdict=critic_output.verdict, attempt=attempt)
            break
        except (json.JSONDecodeError, Exception) as exc:
            logger.warning("Critic LLM attempt failed", attempt=attempt, error=str(exc))

    if critic_output is None:
        # If we can't get a Critic verdict, default to approved to unblock the pipeline.
        # The human reviewer is the final safety net anyway.
        logger.error("Critic LLM failed; defaulting to approved to unblock human review")
        critic_output = CriticOutput(
            verdict=CriticVerdict.APPROVED,
            feedback="Critic LLM unavailable; patch passed deterministic syntax check only. Human review recommended.",
            syntax_valid=True,
            potential_side_effects=["Critic LLM unavailable – manual review required"],
        )

    return _build_state_after_critic(state, critic_output, logger)


def _build_state_after_critic(
    state: AuditState,
    critic_output: CriticOutput,
    logger: structlog.BoundLogger,
) -> AuditState:
    settings = get_settings()

    if critic_output.verdict == CriticVerdict.APPROVED:
        logger.info("Critic approved patch, routing to human review")
        return state.model_copy(
            update={
                "critic_output": critic_output,
                "current_node": AgentNode.HUMAN_REVIEW,
                "status": AuditStatus.AWAITING_APPROVAL,
            }
        )

    # Rejected: decide whether to retry or abort
    new_retry_count = state.patch_retry_count + 1
    if new_retry_count <= settings.max_patch_retries:
        logger.info(
            "Critic rejected patch, routing back to Patcher",
            retry=new_retry_count,
            max=settings.max_patch_retries,
        )
        return state.model_copy(
            update={
                "critic_output": critic_output,
                "patch_retry_count": new_retry_count,
                "current_node": AgentNode.PATCHER,
                "status": AuditStatus.RUNNING,
            }
        )

    logger.warning("Max patch retries exhausted, marking as failed")
    return state.model_copy(
        update={
            "critic_output": critic_output,
            "current_node": AgentNode.DONE,
            "status": AuditStatus.FAILED,
            "error": f"Critic rejected patch after {settings.max_patch_retries} retries: {critic_output.feedback}",
        }
    )
