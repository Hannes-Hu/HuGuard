"""
Tests for the Patcher and Critic agent execution flows.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch
import pytest
from langchain_core.messages import AIMessage

from app.agents.patcher import run_patcher_node
from app.agents.critic import run_critic_node
from app.schemas.audit import (
    ASTReport,
    AuditState,
    AuditStatus,
    CriticVerdict,
    PatcherOutput,
    ScannerOutput,
    SecurityFinding,
    Severity,
    UnifiedDiff,
)


def _make_state_with_finding(code: str) -> AuditState:
    finding = SecurityFinding(
        id="vuln01",
        title="SQL Injection",
        description="SQL injection in cursor.execute",
        severity=Severity.HIGH,
        category="sql-injection",
        affected_lines=[5],
    )
    return AuditState(
        thread_id="test-agents-thread",
        source_code=code,
        filename="test.py",
        language="python",
        ast_report=ASTReport(
            filename="test.py",
            language="python",
            symbols=[],
            total_lines=10,
            static_findings=[],
        ),
        scanner_output=ScannerOutput(findings=[finding], summary="High vuln", risk_score=80),
        status=AuditStatus.RUNNING,
    )


class TestPatcherNode:
    def test_patcher_success(self, vulnerable_python_code: str) -> None:
        state = _make_state_with_finding(vulnerable_python_code)
        fixed_code = vulnerable_python_code.replace(" + user_id", ", (user_id,)")

        mock_llm = MagicMock()
        mock_llm.invoke.return_value = AIMessage(
            content=json.dumps({
                "finding_id": "vuln01",
                "rationale": "Parameterized query avoids injection",
                "patched_code": fixed_code,
                "is_breaking_change": False,
            })
        )

        with patch("app.agents.patcher.ChatOllama", return_value=mock_llm):
            result = run_patcher_node(state)

        assert result.patcher_output is not None
        assert result.patcher_output.finding_id == "vuln01"
        assert result.patcher_output.diff.patched_snippet == fixed_code

    def test_patcher_no_findings_completes(self) -> None:
        state = AuditState(
            thread_id="test-empty",
            source_code="x = 1\n",
            filename="test.py",
            scanner_output=ScannerOutput(findings=[], summary="clean", risk_score=0),
        )
        result = run_patcher_node(state)
        assert result.status == AuditStatus.COMPLETED


class TestCriticNode:
    def test_critic_syntax_error_short_circuits(self, vulnerable_python_code: str) -> None:
        state = _make_state_with_finding(vulnerable_python_code)
        state = state.model_copy(update={
            "patcher_output": PatcherOutput(
                finding_id="vuln01",
                rationale="Broken syntax test rationale that satisfies minimum length requirement",
                diff=UnifiedDiff(
                    original_snippet=vulnerable_python_code,
                    patched_snippet="def broken(\n",  # Invalid syntax
                    unified_diff="",
                    affected_lines=[],
                ),
                is_breaking_change=False,
            )
        })

        result = run_critic_node(state)
        assert result.critic_output is not None
        assert result.critic_output.verdict == CriticVerdict.REJECTED
        assert result.critic_output.syntax_valid is False
        assert "SyntaxError" in result.critic_output.feedback

    def test_critic_approved_via_llm(self, vulnerable_python_code: str) -> None:
        state = _make_state_with_finding(vulnerable_python_code)
        state = state.model_copy(update={
            "patcher_output": PatcherOutput(
                finding_id="vuln01",
                rationale="Valid fix rationale that satisfies minimum length requirement",
                diff=UnifiedDiff(
                    original_snippet=vulnerable_python_code,
                    patched_snippet="def safe(): pass\n",
                    unified_diff="",
                    affected_lines=[],
                ),
                is_breaking_change=False,
            )
        })

        mock_llm = MagicMock()
        mock_llm.invoke.return_value = AIMessage(
            content=json.dumps({
                "verdict": "approved",
                "feedback": "Correct fix with no regressions",
                "syntax_valid": True,
                "potential_side_effects": [],
            })
        )

        with patch("app.agents.critic.ChatOllama", return_value=mock_llm):
            result = run_critic_node(state)

        assert result.critic_output is not None
        assert result.critic_output.verdict == CriticVerdict.APPROVED
