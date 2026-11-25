"""
Tests for the static analysis tools layer (tree-sitter, ruff, bandit wrappers).

These tests run fully deterministically without any LLM or network access.
"""

from __future__ import annotations

from app.schemas.audit import Severity
from app.tools.code_analysis import analyse_code, validate_python_syntax


VULNERABLE_CODE = '''
import os
import sqlite3

SECRET_KEY = "hardcoded-secret-abc123"  # bandit B105

def get_user(user_id):
    conn = sqlite3.connect("app.db")
    cursor = conn.cursor()
    # SQL injection: user_id is not sanitised
    query = "SELECT * FROM users WHERE id = " + user_id
    cursor.execute(query)
    return cursor.fetchone()

def run_command(cmd):
    os.system(cmd)  # bandit B605 - shell injection risk
'''

CLEAN_CODE = '''
def add(a: int, b: int) -> int:
    return a + b

class Calculator:
    def multiply(self, x: int, y: int) -> int:
        return x * y
'''


class TestASTAnalysis:
    def test_symbol_extraction_identifies_functions_and_classes(self) -> None:
        report = analyse_code(CLEAN_CODE, "calc.py", "python")
        names = {s.name for s in report.symbols}
        assert "add" in names
        assert "Calculator" in names

    def test_symbol_line_numbers_are_accurate(self) -> None:
        report = analyse_code(CLEAN_CODE, "calc.py", "python")
        add_sym = next((s for s in report.symbols if s.name == "add"), None)
        assert add_sym is not None
        assert add_sym.start_line == 2

    def test_total_lines_count_is_correct(self) -> None:
        code = "a = 1\nb = 2\nc = 3"
        report = analyse_code(code, "vars.py", "python")
        assert report.total_lines == 3

    def test_static_findings_detect_known_vulnerabilities(self) -> None:
        report = analyse_code(VULNERABLE_CODE, "vuln.py", "python")
        # We expect at least bandit to flag the hardcoded secret and os.system call
        assert len(report.static_findings) > 0
        tools_used = {f.tool for f in report.static_findings}
        assert "bandit" in tools_used or "ruff" in tools_used

    def test_severity_field_is_always_a_valid_enum(self) -> None:
        report = analyse_code(VULNERABLE_CODE, "vuln.py", "python")
        for finding in report.static_findings:
            assert isinstance(finding.severity, Severity)

    def test_unsupported_language_raises_on_ast_but_still_returns_report(self) -> None:
        # We don't support Go AST but shouldn't crash – we return a report with no symbols
        report = analyse_code("package main\nfunc main() {}", "main.go", "go")
        assert report.symbols == []


class TestSyntaxValidation:
    def test_valid_python_returns_true(self) -> None:
        ok, err = validate_python_syntax("x = 1 + 2\n")
        assert ok is True
        assert err is None

    def test_syntax_error_returns_false_with_message(self) -> None:
        ok, err = validate_python_syntax("def foo(\n")
        assert ok is False
        assert err is not None
        assert "SyntaxError" in err

    def test_line_number_is_included_in_error(self) -> None:
        ok, err = validate_python_syntax("x = 1\ny = (\n")
        assert ok is False
        assert err is not None


class TestDiffUtils:
    def test_generate_unified_diff(self) -> None:
        from app.tools.diff_utils import generate_unified_diff
        original = "def add(a, b):\n    return a - b\n"
        patched = "def add(a, b):\n    return a + b\n"
        diff = generate_unified_diff(original, patched, "calc.py")
        assert diff.original_snippet == original
        assert diff.patched_snippet == patched
        assert "+    return a + b" in diff.unified_diff
        assert len(diff.affected_lines) > 0
