"""
All Pydantic v2 schemas used across API I/O, LangGraph state, and SSE events.

Keeping schemas in one place prevents the classic "two Pydantic models for the
same concept" drift that happens when routers and agents evolve independently.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum
from typing import Annotated, Any

from pydantic import BaseModel, Field, field_validator


# ── Enumerations ──────────────────────────────────────────────────────────────

class Severity(str, Enum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INFO = "info"


class AgentNode(str, Enum):
    SCANNER = "scanner"
    PATCHER = "patcher"
    CRITIC = "critic"
    HUMAN_REVIEW = "human_review"
    DONE = "done"


class AuditStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    AWAITING_APPROVAL = "awaiting_approval"
    APPROVED = "approved"
    REJECTED = "rejected"
    COMPLETED = "completed"
    FAILED = "failed"


class ApprovalDecision(str, Enum):
    APPROVE = "approve"
    REJECT = "reject"


# ── Code Analysis Primitives ──────────────────────────────────────────────────

class CodeSymbol(BaseModel):
    """A function or class extracted from AST analysis."""

    name: str
    kind: str  # "function" | "class" | "method"
    start_line: int
    end_line: int
    complexity: int = Field(default=1, ge=1)


class StaticFinding(BaseModel):
    """A single issue reported by ruff or bandit."""

    tool: str  # "ruff" | "bandit"
    rule_id: str
    message: str
    filename: str
    line: int
    col: int
    severity: Severity


class ASTReport(BaseModel):
    """Output of tree-sitter analysis on a single file."""

    filename: str
    language: str
    symbols: list[CodeSymbol]
    total_lines: int
    static_findings: list[StaticFinding]


# ── Agent Output Schemas (used with with_structured_output) ──────────────────
# These are what the LLM must emit. Strict models = deterministic agent output.

class SecurityFinding(BaseModel):
    """A vulnerability or code quality issue identified by the Scanner agent."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4())[:8])
    title: str = Field(min_length=5, max_length=200)
    description: str = Field(min_length=10)
    severity: Severity
    category: str  # e.g. "sql-injection", "hardcoded-secret", "architecture"
    affected_lines: list[int] = Field(default_factory=list)
    cwe_id: str | None = Field(default=None)  # e.g. "CWE-89"


class ScannerOutput(BaseModel):
    """Full output of the Scanner & Triage agent node."""

    findings: list[SecurityFinding]
    summary: str
    risk_score: Annotated[int, Field(ge=0, le=100)]


class UnifiedDiff(BaseModel):
    """A unified-format diff produced by the Patcher agent."""

    original_snippet: str
    patched_snippet: str
    # We store both so the frontend diff-viewer doesn't have to reconstruct them
    unified_diff: str
    affected_lines: list[int]


class PatcherOutput(BaseModel):
    """Output of the Patch Generator agent node."""

    finding_id: str
    rationale: str = Field(min_length=20)
    diff: UnifiedDiff
    # Whether the patch changes public API surface (helps the Critic prioritise)
    is_breaking_change: bool = Field(default=False)


class CriticVerdict(str, Enum):
    APPROVED = "approved"
    REJECTED = "rejected"


class CriticOutput(BaseModel):
    """Output of the Critic & Verifier agent node."""

    verdict: CriticVerdict
    # Specific, actionable feedback so the Patcher knows exactly what to fix
    feedback: str
    syntax_valid: bool
    # Detected side-effects the original patch author may have missed
    potential_side_effects: list[str] = Field(default_factory=list)


# ── LangGraph State ───────────────────────────────────────────────────────────

class AuditState(BaseModel):
    """
    The single source of truth flowing through every LangGraph node.

    LangGraph serialises this into the SQLite checkpoint store between node
    executions, so every field must be JSON-serialisable. Using a typed
    Pydantic model (rather than a plain TypedDict) gives us runtime validation
    on every state transition.
    """

    thread_id: str
    source_code: str
    filename: str
    language: str = "python"

    # Populated progressively as the graph advances
    ast_report: ASTReport | None = None
    scanner_output: ScannerOutput | None = None
    patcher_output: PatcherOutput | None = None
    critic_output: CriticOutput | None = None

    # Retry counter – the graph increments this before each Patcher re-run
    patch_retry_count: int = Field(default=0, ge=0)

    current_node: AgentNode = AgentNode.SCANNER
    status: AuditStatus = AuditStatus.PENDING

    # Set by the human-in-the-loop endpoint
    approval_decision: ApprovalDecision | None = None
    approval_comment: str | None = None

    error: str | None = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    @field_validator("source_code")
    @classmethod
    def _reject_empty_source(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("source_code must not be blank")
        return v


# ── API Request / Response Models ─────────────────────────────────────────────

class AuditStartRequest(BaseModel):
    """Body for POST /api/v1/audit/start when sending a raw snippet."""

    source_code: str = Field(min_length=1)
    filename: str = Field(default="snippet.py", min_length=1)
    language: str = Field(default="python")


class AuditStartResponse(BaseModel):
    thread_id: str
    status: AuditStatus
    message: str


class ApprovalRequest(BaseModel):
    decision: ApprovalDecision
    comment: str | None = Field(default=None, max_length=1000)


class AuditSummaryResponse(BaseModel):
    thread_id: str
    status: AuditStatus
    scanner_output: ScannerOutput | None
    patcher_output: PatcherOutput | None
    critic_output: CriticOutput | None
    patch_retry_count: int
    error: str | None
    created_at: datetime
    updated_at: datetime


# ── SSE Event Schemas ─────────────────────────────────────────────────────────

class SSEEventType(str, Enum):
    NODE_START = "node_start"
    NODE_COMPLETE = "node_complete"
    FINDING = "finding"
    PATCH_READY = "patch_ready"
    CRITIC_VERDICT = "critic_verdict"
    AWAITING_HUMAN = "awaiting_human"
    RETRY = "retry"
    COMPLETED = "completed"
    ERROR = "error"
    HEARTBEAT = "heartbeat"


class SSEEvent(BaseModel):
    event: SSEEventType
    thread_id: str
    node: AgentNode | None = None
    data: dict[str, Any] = Field(default_factory=dict)
    timestamp: datetime = Field(default_factory=datetime.utcnow)
