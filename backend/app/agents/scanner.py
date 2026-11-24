"""
Scanner & Triage Agent.

Receives static analysis results and asks the LLM to reason about *actual*
exploitability and impact – the kind of contextual judgment that bandit/ruff
can't make on their own (e.g. "is this SQL string actually user-controlled?").
"""

from __future__ import annotations

import json

import structlog
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_ollama import ChatOllama

from app.core.config import get_settings
from app.schemas.audit import (
    AgentNode,
    ASTReport,
    AuditState,
    AuditStatus,
    ScannerOutput,
    SecurityFinding,
    Severity,
)

log = structlog.get_logger(__name__)

_SYSTEM_PROMPT = """\
You are a senior application security engineer performing a code audit.
You will be given source code and static analysis results (from ruff and bandit).
Your job is to identify real security vulnerabilities, bugs, and architectural
weaknesses that an attacker or bug could actually exploit.

Rules:
- Focus on exploitable issues, not style nits.
- Assign severity based on actual impact, not tool severity.
- For each finding, cite the specific lines involved.
- If a static tool finding is a false positive given the context, omit it.
- Respond ONLY with valid JSON matching the ScannerOutput schema. No prose.
"""


def _build_scanner_prompt(source_code: str, ast_report: ASTReport) -> str:
    findings_summary = "\n".join(
        f"  [{f.tool}] Line {f.line}: ({f.rule_id}) {f.message}"
        for f in ast_report.static_findings
    )
    symbols_summary = "\n".join(
        f"  {s.kind} {s.name!r} [L{s.start_line}-{s.end_line}] complexity={s.complexity}"
        for s in ast_report.symbols
    )
    return f"""
FILE: {ast_report.filename} ({ast_report.language}, {ast_report.total_lines} lines)

SYMBOLS:
{symbols_summary or "  (none extracted)"}

STATIC ANALYSIS FINDINGS:
{findings_summary or "  (none)"}

SOURCE CODE:
```
{source_code}
```

Analyse the above and return a JSON object with this exact structure:
{{
  "findings": [
    {{
      "id": "<8-char-hex>",
      "title": "<concise title>",
      "description": "<what the issue is and how it can be exploited>",
      "severity": "critical|high|medium|low|info",
      "category": "<e.g. sql-injection|hardcoded-secret|path-traversal|...>",
      "affected_lines": [<list of line numbers>],
      "cwe_id": "<CWE-NNN or null>"
    }}
  ],
  "summary": "<2-3 sentence executive summary>",
  "risk_score": <0-100>
}}
"""


def _fallback_scanner_output(source_code: str, ast_report: ASTReport) -> ScannerOutput:
    """
    When the LLM fails to produce valid JSON after retries, we fall back to
    a deterministic output derived purely from bandit/ruff findings.
    This ensures the pipeline keeps moving rather than hard-failing.
    """
    findings = [
        SecurityFinding(
            id=f"fallback-{i:04d}",
            title=f.message[:100],
            description=f"Detected by {f.tool} rule {f.rule_id}: {f.message}",
            severity=f.severity,
            category=f.rule_id,
            affected_lines=[f.line],
            cwe_id=None,
        )
        for i, f in enumerate(ast_report.static_findings)
    ]
    return ScannerOutput(
        findings=findings,
        summary="LLM analysis unavailable; results derived from static tools only.",
        risk_score=min(len(findings) * 10, 100),
    )


def run_scanner_node(state: AuditState) -> AuditState:
    """
    LangGraph node: Scanner & Triage.

    Takes the AST report already in state and asks the LLM to produce a
    prioritised finding list. On LLM failure, falls back to static-only output.
    """
    settings = get_settings()
    logger = log.bind(thread_id=state.thread_id, node="scanner")
    logger.info("Scanner node started")

    if state.ast_report is None:
        # This should never happen if the graph is wired correctly
        raise RuntimeError("Scanner node called without ast_report in state")

    llm = ChatOllama(
        base_url=settings.ollama_base_url,
        model=settings.ollama_model,
        temperature=settings.ollama_temperature,
        timeout=settings.llm_timeout_seconds,
        format="json",
    )

    prompt = _build_scanner_prompt(state.source_code, state.ast_report)
    messages = [SystemMessage(content=_SYSTEM_PROMPT), HumanMessage(content=prompt)]

    scanner_output: ScannerOutput | None = None
    max_attempts = 3

    for attempt in range(1, max_attempts + 1):
        try:
            response = llm.invoke(messages)
            raw = response.content
            if isinstance(raw, list):
                # Some Ollama versions return a list of content blocks
                raw = " ".join(str(b) for b in raw)
            data = json.loads(raw)
            scanner_output = ScannerOutput.model_validate(data)
            logger.info("Scanner LLM call succeeded", attempt=attempt, findings=len(scanner_output.findings))
            break
        except (json.JSONDecodeError, Exception) as exc:
            logger.warning("Scanner LLM attempt failed", attempt=attempt, error=str(exc))

    if scanner_output is None:
        logger.error("All scanner LLM attempts failed, using fallback")
        scanner_output = _fallback_scanner_output(state.source_code, state.ast_report)

    return state.model_copy(
        update={
            "scanner_output": scanner_output,
            "current_node": AgentNode.PATCHER,
            "status": AuditStatus.RUNNING,
        }
    )
