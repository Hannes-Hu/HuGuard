"""
Diff generation utilities for the Patcher agent.

We produce unified diffs ourselves rather than delegating to the LLM because:
1. The LLM is bad at diff syntax (off-by-one context lines, wrong headers)
2. We need machine-parseable diffs for the frontend diff viewer
3. The Critic can re-validate the diff independently of the LLM's claim
"""

from __future__ import annotations

import difflib

from app.schemas.audit import UnifiedDiff


def generate_unified_diff(
    original: str,
    patched: str,
    filename: str = "code.py",
    context_lines: int = 3,
) -> UnifiedDiff:
    """
    Generate a proper unified diff between two code strings.

    We use difflib rather than calling `diff` as a subprocess so there's no
    platform dependency and we stay in-process.
    """
    original_lines = original.splitlines(keepends=True)
    patched_lines = patched.splitlines(keepends=True)

    diff_lines = list(
        difflib.unified_diff(
            original_lines,
            patched_lines,
            fromfile=f"a/{filename}",
            tofile=f"b/{filename}",
            n=context_lines,
        )
    )

    unified = "".join(diff_lines)

    # Collect line numbers that actually changed (+ or - prefixed lines)
    affected: list[int] = []
    current_line = 0
    for line in diff_lines:
        if line.startswith("@@"):
            # Parse the @@ -start,count +start,count @@ header
            try:
                parts = line.split("+")[1].split("@@")[0].strip().split(",")
                current_line = int(parts[0])
            except (IndexError, ValueError):
                pass
        elif line.startswith("+") and not line.startswith("+++"):
            affected.append(current_line)
            current_line += 1
        elif line.startswith("-") and not line.startswith("---"):
            pass  # deletion: don't advance new-file line counter
        else:
            current_line += 1

    return UnifiedDiff(
        original_snippet=original,
        patched_snippet=patched,
        unified_diff=unified,
        affected_lines=sorted(set(affected)),
    )
