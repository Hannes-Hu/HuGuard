"""
Tree-sitter AST analysis + ruff + bandit static checks.

These tools run synchronously and deterministically *before* any LLM call.
The output constrains what the Scanner agent needs to reason about, which
reduces hallucination and keeps prompts focused.
"""

from __future__ import annotations

import ast
import json
import subprocess
import tempfile
from pathlib import Path

import structlog
import tree_sitter_python as tspython
import tree_sitter_javascript as tsjavascript
from tree_sitter import Language, Node, Parser

from app.schemas.audit import (
    ASTReport,
    CodeSymbol,
    Severity,
    StaticFinding,
)

log = structlog.get_logger(__name__)

# Build language objects once at module load – Parser construction is cheap
# but Language.build_library writes to disk, so we use the pre-compiled wheels.
_PY_LANGUAGE = Language(tspython.language())
_JS_LANGUAGE = Language(tsjavascript.language())


def _get_parser(language: str) -> Parser:
    lang_map = {
        "python": _PY_LANGUAGE,
        "javascript": _JS_LANGUAGE,
        "typescript": _JS_LANGUAGE,  # ts grammar is a superset of js for our purposes
    }
    parser = Parser(_get_language(language))
    return parser


def _get_language(language: str) -> Language:
    lang_map: dict[str, Language] = {
        "python": _PY_LANGUAGE,
        "javascript": _JS_LANGUAGE,
        "typescript": _JS_LANGUAGE,
    }
    lang = lang_map.get(language.lower())
    if lang is None:
        raise ValueError(f"Unsupported language for AST analysis: {language!r}")
    return lang


# ── Symbol extraction ─────────────────────────────────────────────────────────

def _extract_symbols(root: Node, source: bytes) -> list[CodeSymbol]:
    """Walk the tree and collect function/class definitions."""
    symbols: list[CodeSymbol] = []
    _walk(root, source, symbols)
    return symbols


def _walk(node: Node, source: bytes, acc: list[CodeSymbol]) -> None:
    target_kinds = {
        "function_definition",
        "class_definition",
        "function_declaration",
        "method_definition",
        "arrow_function",
    }
    if node.type in target_kinds:
        # Name extraction differs between Python and JS grammar node shapes
        name_node = node.child_by_field_name("name")
        name = name_node.text.decode() if name_node and name_node.text else "<anonymous>"
        kind = "function" if "function" in node.type else "class"
        acc.append(
            CodeSymbol(
                name=name,
                kind=kind,
                start_line=node.start_point[0] + 1,
                end_line=node.end_point[0] + 1,
                complexity=_estimate_complexity(node),
            )
        )
    for child in node.children:
        _walk(child, source, acc)


def _estimate_complexity(node: Node) -> int:
    """
    Approximate cyclomatic complexity by counting branch-introducing node types.
    Not a substitute for a proper McCabe analyser, but good enough to flag
    high-complexity functions for the Scanner agent to prioritise.
    """
    branch_types = {
        "if_statement", "elif_clause", "for_statement", "while_statement",
        "try_statement", "except_clause", "with_statement",
        "if_statement", "switch_statement", "catch_clause",
        "conditional_expression", "ternary_expression",
    }
    count = 1  # baseline
    for child in node.children:
        if child.type in branch_types:
            count += 1
        count += _estimate_complexity(child) - 1
    return max(1, count)


# ── Ruff ──────────────────────────────────────────────────────────────────────

def _run_ruff(source_code: str, filename: str) -> list[StaticFinding]:
    findings: list[StaticFinding] = []
    with tempfile.NamedTemporaryFile(
        suffix=Path(filename).suffix or ".py",
        mode="w",
        encoding="utf-8",
        delete=False,
    ) as tmp:
        tmp.write(source_code)
        tmp_path = tmp.name

    try:
        result = subprocess.run(
            ["ruff", "check", tmp_path, "--output-format=json", "--no-cache"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.stdout:
            raw: list[dict] = json.loads(result.stdout)
            for item in raw:
                rule_id = item.get("code") or "unknown"
                findings.append(
                    StaticFinding(
                        tool="ruff",
                        rule_id=rule_id,
                        message=item.get("message", ""),
                        filename=filename,
                        line=item.get("location", {}).get("row", 0),
                        col=item.get("location", {}).get("column", 0),
                        # Ruff doesn't expose severity – we map error codes
                        severity=_ruff_severity(rule_id),
                    )
                )
    except subprocess.TimeoutExpired:
        log.warning("ruff timed out", filename=filename)
    except json.JSONDecodeError:
        log.warning("ruff returned non-JSON output", stdout=result.stdout[:200])
    finally:
        Path(tmp_path).unlink(missing_ok=True)

    return findings


def _ruff_severity(code: str | None) -> Severity:
    if not code:
        return Severity.LOW
    # S-prefixed rules are flake8-bandit security rules; treat as HIGH
    if code.startswith("S"):
        return Severity.HIGH
    if code.startswith("E"):
        return Severity.MEDIUM
    return Severity.LOW


# ── Bandit ────────────────────────────────────────────────────────────────────

def _run_bandit(source_code: str, filename: str) -> list[StaticFinding]:
    findings: list[StaticFinding] = []
    # Bandit only analyses Python; skip silently for other languages
    if not filename.endswith(".py"):
        return findings

    with tempfile.NamedTemporaryFile(
        suffix=".py", mode="w", encoding="utf-8", delete=False
    ) as tmp:
        tmp.write(source_code)
        tmp_path = tmp.name

    try:
        result = subprocess.run(
            ["bandit", "-f", "json", "-ll", tmp_path],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.stdout:
            data = json.loads(result.stdout)
            for issue in data.get("results", []):
                findings.append(
                    StaticFinding(
                        tool="bandit",
                        rule_id=issue.get("test_id", "unknown"),
                        message=issue.get("issue_text", ""),
                        filename=filename,
                        line=issue.get("line_number", 0),
                        col=0,
                        severity=_bandit_severity(issue.get("issue_severity", "LOW")),
                    )
                )
    except subprocess.TimeoutExpired:
        log.warning("bandit timed out", filename=filename)
    except json.JSONDecodeError:
        log.warning("bandit returned non-JSON output")
    finally:
        Path(tmp_path).unlink(missing_ok=True)

    return findings


def _bandit_severity(level: str) -> Severity:
    return {
        "HIGH": Severity.HIGH,
        "MEDIUM": Severity.MEDIUM,
        "LOW": Severity.LOW,
    }.get(level.upper(), Severity.LOW)


# ── Syntax Validation ─────────────────────────────────────────────────────────

def validate_python_syntax(source_code: str) -> tuple[bool, str | None]:
    """
    Use the stdlib ast module rather than re-running tree-sitter.
    ast.parse raises SyntaxError with precise line/col info which we surface
    back to the Critic agent as structured feedback.
    """
    try:
        ast.parse(source_code)
        return True, None
    except SyntaxError as exc:
        return False, f"SyntaxError at line {exc.lineno}: {exc.msg}"


# ── Public interface ──────────────────────────────────────────────────────────

def analyse_code(source_code: str, filename: str, language: str = "python") -> ASTReport:
    """
    Run the full static analysis pipeline on a source file.

    Order matters: AST first (cheap), then ruff/bandit (subprocess).
    We merge both tool outputs so the Scanner agent sees everything in one place.
    """
    log.info("Starting static analysis", filename=filename, language=language)

    source_bytes = source_code.encode("utf-8")
    symbols: list[CodeSymbol] = []

    try:
        parser = _get_parser(language)
        tree = parser.parse(source_bytes)
        symbols = _extract_symbols(tree.root_node, source_bytes)
        log.debug("AST extraction complete", symbol_count=len(symbols))
    except (ValueError, Exception) as exc:
        # Non-fatal: we can still run ruff/bandit without tree-sitter symbols
        log.warning("AST parsing failed, continuing without symbols", error=str(exc))

    ruff_findings = _run_ruff(source_code, filename)
    bandit_findings = _run_bandit(source_code, filename)
    all_findings = ruff_findings + bandit_findings

    log.info(
        "Static analysis complete",
        filename=filename,
        symbols=len(symbols),
        findings=len(all_findings),
    )

    return ASTReport(
        filename=filename,
        language=language,
        symbols=symbols,
        total_lines=source_code.count("\n") + 1,
        static_findings=all_findings,
    )
