"""
Patch Generator Agent.

Given the highest-severity finding from the Scanner, generates a concrete
code fix. The LLM produces only the patched code snippet; we compute the
actual unified diff ourselves (see tools/diff_utils.py) for reliability.
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
    PatcherOutput,
    SecurityFinding,
    Severity,
    UnifiedDiff,
)
from app.tools.diff_utils import generate_unified_diff

log = structlog.get_logger(__name__)

_SYSTEM_PROMPT = """\
You are a senior software engineer writing security patches.
Given a vulnerability description and the original source code, produce
a minimal, correct fix that resolves the issue without breaking existing
functionality.

Rules:
- Change only what is necessary to fix the specific vulnerability.
- Preserve the original code style, indentation, and variable names.
- Do not add unrelated refactoring.
- Respond ONLY with valid JSON. No prose, no code fences in your response.
"""

_SEVERITY_ORDER = [
    Severity.CRITICAL,
    Severity.HIGH,
    Severity.MEDIUM,
    Severity.LOW,
    Severity.INFO,
]


def _pick_target_finding(state: AuditState) -> SecurityFinding | None:
    """
    Select the highest-severity unpatched finding to fix next.

    When retrying (patch_retry_count > 0), the Critic's feedback is already
    in state, so the Patcher will re-read it and attempt a corrected patch
    for the same finding. We therefore always pick the same finding on retries.
    """
    if state.scanner_output is None or not state.scanner_output.findings:
        return None
    # Sort by our enum order (not alphabetically)
    ordered = sorted(
        state.scanner_output.findings,
        key=lambda f: _SEVERITY_ORDER.index(f.severity) if f.severity in _SEVERITY_ORDER else 99,
    )
    return ordered[0]


def _build_patcher_prompt(
    finding: SecurityFinding,
    source_code: str,
    filename: str,
    critic_feedback: str | None,
) -> str:
    retry_note = ""
    if critic_feedback:
        retry_note = f"\n\nPREVIOUS PATCH WAS REJECTED. CRITIC FEEDBACK:\n{critic_feedback}\nAddress all feedback points in this new attempt.\n"

    return f"""
VULNERABILITY TO FIX:
  ID: {finding.id}
  Title: {finding.title}
  Severity: {finding.severity.value}
  Description: {finding.description}
  Affected lines: {finding.affected_lines}
  CWE: {finding.cwe_id or 'N/A'}
{retry_note}
ORIGINAL SOURCE CODE ({filename}):
```
{source_code}
```

Return a JSON object with this exact structure:
{{
  "finding_id": "{finding.id}",
  "rationale": "<explain the vulnerability and why your fix resolves it>",
  "patched_code": "<the COMPLETE fixed source file content, not just the changed lines>",
  "is_breaking_change": false
}}
"""


def run_patcher_node(state: AuditState) -> AuditState:
    """
    LangGraph node: Patch Generator.

    On retry (critic rejected), the previous critic feedback is included in
    the prompt so the LLM can self-correct.
    """
    settings = get_settings()
    logger = log.bind(thread_id=state.thread_id, node="patcher", retry=state.patch_retry_count)
    logger.info("Patcher node started")

    finding = _pick_target_finding(state)
    if finding is None:
        logger.info("No findings to patch, skipping to done")
        return state.model_copy(
            update={"current_node": AgentNode.DONE, "status": AuditStatus.COMPLETED}
        )

    critic_feedback: str | None = None
    if state.critic_output is not None and state.patch_retry_count > 0:
        critic_feedback = state.critic_output.feedback

    llm = ChatOllama(
        base_url=settings.ollama_base_url,
        model=settings.ollama_model,
        temperature=settings.ollama_temperature,
        timeout=settings.llm_timeout_seconds,
        format="json",
    )

    prompt = _build_patcher_prompt(finding, state.source_code, state.filename, critic_feedback)
    messages = [SystemMessage(content=_SYSTEM_PROMPT), HumanMessage(content=prompt)]

    patcher_output: PatcherOutput | None = None
    max_attempts = 3

    for attempt in range(1, max_attempts + 1):
        try:
            response = llm.invoke(messages)
            raw = response.content
            if isinstance(raw, list):
                raw = " ".join(str(b) for b in raw)
            data = json.loads(raw)

            patched_code: str = data["patched_code"]
            diff: UnifiedDiff = generate_unified_diff(
                original=state.source_code,
                patched=patched_code,
                filename=state.filename,
            )
            patcher_output = PatcherOutput(
                finding_id=finding.id,
                rationale=data["rationale"],
                diff=diff,
                is_breaking_change=bool(data.get("is_breaking_change", False)),
            )
            logger.info("Patcher LLM call succeeded", attempt=attempt)
            break
        except (KeyError, json.JSONDecodeError, Exception) as exc:
            logger.warning("Patcher LLM attempt failed", attempt=attempt, error=str(exc))

    if patcher_output is None:
        logger.error("All patcher LLM attempts failed")
        # Surface the error but don't crash the graph
        return state.model_copy(
            update={
                "error": "Patcher agent failed to generate a valid patch after all retries.",
                "current_node": AgentNode.DONE,
                "status": AuditStatus.FAILED,
            }
        )

    return state.model_copy(
        update={
            "patcher_output": patcher_output,
            "current_node": AgentNode.CRITIC,
            "status": AuditStatus.RUNNING,
        }
    )
