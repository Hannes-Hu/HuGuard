"""
Tests for the Scanner agent node.

We mock ChatOllama.invoke to control LLM output deterministically.
The tests verify schema validation, fallback behaviour, and state transitions.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest
from langchain_core.messages import AIMessage

from app.agents.scanner import run_scanner_node
from app.schemas.audit import ASTReport, AuditState, AuditStatus, Severity


def _make_state(source_code: str, ast_report: ASTReport) -> AuditState:
    return AuditState(
        thread_id="test-thread-scanner",
        source_code=source_code,
        filename="vuln.py",
        language="python",
        ast_report=ast_report,
        status=AuditStatus.RUNNING,
    )


def _make_ast_report() -> ASTReport:
    return ASTReport(
        filename="vuln.py",
        language="python",
        symbols=[],
        total_lines=10,
        static_findings=[],
    )


class TestScannerNode:
    def test_valid_llm_response_populates_scanner_output(
        self, vulnerable_python_code: str, scanner_llm_response: str
    ) -> None:
        state = _make_state(vulnerable_python_code, _make_ast_report())

        mock_llm = MagicMock()
        mock_llm.invoke.return_value = AIMessage(content=scanner_llm_response)

        with patch("app.agents.scanner.ChatOllama", return_value=mock_llm):
            result = run_scanner_node(state)

        assert result.scanner_output is not None
        assert len(result.scanner_output.findings) == 1
        assert result.scanner_output.findings[0].severity == Severity.CRITICAL
        assert result.scanner_output.risk_score == 90

    def test_invalid_json_triggers_fallback_output(
        self, vulnerable_python_code: str
    ) -> None:
        """
        When the LLM returns malformed JSON on all attempts, the scanner must
        fall back to static-only findings rather than raising an exception.
        This keeps the pipeline alive under degraded LLM conditions.
        """
        from app.schemas.audit import StaticFinding

        static_finding = StaticFinding(
            tool="bandit",
            rule_id="B608",
            message="Possible SQL injection",
            filename="vuln.py",
            line=11,
            col=0,
            severity=Severity.HIGH,
        )
        ast_report = ASTReport(
            filename="vuln.py",
            language="python",
            symbols=[],
            total_lines=10,
            static_findings=[static_finding],
        )
        state = _make_state(vulnerable_python_code, ast_report)

        mock_llm = MagicMock()
        mock_llm.invoke.return_value = AIMessage(content="this is not json {{{{")

        with patch("app.agents.scanner.ChatOllama", return_value=mock_llm):
            result = run_scanner_node(state)

        assert result.scanner_output is not None
        # Fallback should surface the bandit finding
        assert len(result.scanner_output.findings) == 1
        assert "LLM analysis unavailable" in result.scanner_output.summary

    def test_raises_if_ast_report_missing(self, vulnerable_python_code: str) -> None:
        state = AuditState(
            thread_id="test-thread",
            source_code=vulnerable_python_code,
            filename="vuln.py",
            language="python",
            ast_report=None,
        )
        with pytest.raises(RuntimeError, match="ast_report"):
            run_scanner_node(state)
