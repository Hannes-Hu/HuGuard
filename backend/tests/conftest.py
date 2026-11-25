"""
Shared pytest fixtures.

We mock the LLM at the langchain_ollama.ChatOllama level so tests run
completely offline and deterministically, regardless of whether Ollama
is running on the developer's machine.
"""

from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import pytest
from langchain_core.messages import AIMessage

# Point tests at a fresh in-memory SQLite DB to avoid polluting the dev DB
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./test_huguard.db")
os.environ.setdefault("OLLAMA_BASE_URL", "http://localhost:11434")
os.environ.setdefault("OLLAMA_MODEL", "qwen2.5-coder:7b")
os.environ.setdefault("SECRET_KEY", "test-secret-key")
os.environ.setdefault("LOG_LEVEL", "ERROR")

# Import after env vars are set so pydantic-settings picks them up
from app.core.config import get_settings  # noqa: E402

get_settings.cache_clear()


@pytest.fixture
def scanner_llm_response() -> str:
    """Minimal valid ScannerOutput JSON that passes schema validation."""
    return """{
        "findings": [
            {
                "id": "abc12345",
                "title": "SQL Injection via string concatenation",
                "description": "User input is directly interpolated into a SQL query string, enabling injection attacks.",
                "severity": "critical",
                "category": "sql-injection",
                "affected_lines": [12, 13],
                "cwe_id": "CWE-89"
            }
        ],
        "summary": "Critical SQL injection vulnerability found on line 12.",
        "risk_score": 90
    }"""


@pytest.fixture
def patcher_llm_response(vulnerable_python_code: str) -> str:
    fixed = vulnerable_python_code.replace(
        'query = "SELECT * FROM users WHERE id = " + user_id',
        'query = "SELECT * FROM users WHERE id = %s"\n    cursor.execute(query, (user_id,))',
    )
    import json
    return json.dumps({
        "finding_id": "abc12345",
        "rationale": "Replaced string concatenation with parameterised query to prevent SQL injection.",
        "patched_code": fixed,
        "is_breaking_change": False,
    })


@pytest.fixture
def critic_approved_response() -> str:
    return """{
        "verdict": "approved",
        "feedback": "Parameterised query correctly fixes the injection. No regressions detected.",
        "syntax_valid": true,
        "potential_side_effects": []
    }"""


@pytest.fixture
def critic_rejected_response() -> str:
    return """{
        "verdict": "rejected",
        "feedback": "The patch introduced an undefined variable `cursor`. Fix the scope issue.",
        "syntax_valid": true,
        "potential_side_effects": ["cursor variable may not be in scope"]
    }"""


@pytest.fixture
def vulnerable_python_code() -> str:
    return '''import sqlite3

def get_user(user_id: str) -> dict:
    conn = sqlite3.connect("app.db")
    cursor = conn.cursor()
    query = "SELECT * FROM users WHERE id = " + user_id
    cursor.execute(query)
    return cursor.fetchone()
'''


@pytest.fixture
def mock_ollama_llm(scanner_llm_response: str):
    """
    Patch ChatOllama.invoke to return controlled responses.
    We patch at the import site in each agent module, not at the source,
    to avoid import-order races.
    """
    mock = MagicMock()
    mock.invoke.return_value = AIMessage(content=scanner_llm_response)
    with patch("app.agents.scanner.ChatOllama", return_value=mock):
        yield mock
