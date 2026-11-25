"""
LangGraph audit graph – the core agentic state machine.

Architecture decisions:
- StateGraph over MessageGraph: our state is richer than a message list and
  we need fine-grained conditional routing (retry loops, human interrupt).
- SqliteSaver for checkpoints: zero-config persistence that survives restarts
  and lets us resume a paused thread from the human-approval endpoint.
- interrupt_before=["human_review"]: LangGraph pauses the graph BEFORE
  executing that node, so the graph is in a stable, resumable state while
  we wait for the user. The state at that point already contains the approved
  patch from the Critic.
- We pass the compiled graph (not a new instance per request) to avoid
  re-compiling on every audit – compilation is surprisingly expensive.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from pathlib import Path
from typing import Any

import aiosqlite
import structlog
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.graph import END, StateGraph

from app.agents.critic import run_critic_node
from app.agents.patcher import run_patcher_node
from app.agents.scanner import run_scanner_node
from app.core.config import get_settings
from app.schemas.audit import (
    AgentNode,
    ApprovalDecision,
    AuditState,
    AuditStatus,
    SSEEvent,
    SSEEventType,
)
from app.tools.code_analysis import analyse_code

log = structlog.get_logger(__name__)


# ── Node wrappers ─────────────────────────────────────────────────────────────
# LangGraph nodes receive and return a dict, not our Pydantic model.
# These thin wrappers handle the serialisation boundary.

def _ingest_node(state_dict: dict[str, Any]) -> dict[str, Any]:
    state = AuditState.model_validate(state_dict)
    ast_report = analyse_code(state.source_code, state.filename, state.language)
    updated = state.model_copy(
        update={
            "ast_report": ast_report,
            "current_node": AgentNode.SCANNER,
            "status": AuditStatus.RUNNING,
        }
    )
    return updated.model_dump(mode="json")


def _scanner_node(state_dict: dict[str, Any]) -> dict[str, Any]:
    state = AuditState.model_validate(state_dict)
    updated = run_scanner_node(state)
    return updated.model_dump(mode="json")


def _patcher_node(state_dict: dict[str, Any]) -> dict[str, Any]:
    state = AuditState.model_validate(state_dict)
    updated = run_patcher_node(state)
    return updated.model_dump(mode="json")


def _critic_node(state_dict: dict[str, Any]) -> dict[str, Any]:
    state = AuditState.model_validate(state_dict)
    updated = run_critic_node(state)
    return updated.model_dump(mode="json")


def _human_review_node(state_dict: dict[str, Any]) -> dict[str, Any]:
    """
    This node is never actually *executed* during the first pass.
    LangGraph interrupts BEFORE it runs. It executes only when the graph is
    resumed via the approval endpoint, at which point we finalise the state.
    """
    state = AuditState.model_validate(state_dict)

    if state.approval_decision == ApprovalDecision.APPROVE:
        updated = state.model_copy(
            update={"current_node": AgentNode.DONE, "status": AuditStatus.APPROVED}
        )
    else:
        updated = state.model_copy(
            update={"current_node": AgentNode.DONE, "status": AuditStatus.REJECTED}
        )
    return updated.model_dump(mode="json")


# ── Routing ───────────────────────────────────────────────────────────────────

def _route_after_patcher(state_dict: dict[str, Any]) -> str:
    state = AuditState.model_validate(state_dict)
    if state.status == AuditStatus.FAILED:
        return END
    if state.current_node == AgentNode.DONE:
        return END
    return "critic"


def _route_after_critic(state_dict: dict[str, Any]) -> str:
    state = AuditState.model_validate(state_dict)
    if state.status == AuditStatus.FAILED:
        return END
    if state.current_node == AgentNode.PATCHER:
        # Critic rejected and retry budget remains
        return "patcher"
    if state.current_node == AgentNode.HUMAN_REVIEW:
        return "human_review"
    return END


# ── Graph construction ────────────────────────────────────────────────────────

def _build_graph() -> StateGraph:
    """
    Build and compile the LangGraph StateGraph.

    Node execution order:
      ingest → scanner → patcher → critic ─→ human_review → END
                                   ↑       |
                                   └───────┘  (on critic reject + retry budget)
    """
    builder = StateGraph(dict)

    builder.add_node("ingest", _ingest_node)
    builder.add_node("scanner", _scanner_node)
    builder.add_node("patcher", _patcher_node)
    builder.add_node("critic", _critic_node)
    builder.add_node("human_review", _human_review_node)

    builder.set_entry_point("ingest")
    builder.add_edge("ingest", "scanner")
    builder.add_edge("scanner", "patcher")

    builder.add_conditional_edges(
        "patcher",
        _route_after_patcher,
        {"critic": "critic", END: END},
    )
    builder.add_conditional_edges(
        "critic",
        _route_after_critic,
        {"patcher": "patcher", "human_review": "human_review", END: END},
    )
    builder.add_edge("human_review", END)

    return builder


# ── Checkpointed graph singleton ──────────────────────────────────────────────

_conn: aiosqlite.Connection | None = None
_saver: AsyncSqliteSaver | None = None
_compiled_graph: Any = None


async def get_graph() -> Any:
    """
    Return the compiled graph with checkpoint persistence.

    We explicitly open and manage an aiosqlite connection to prevent the
    underlying connection worker thread from being re-entered / restarted.
    """
    global _compiled_graph, _saver, _conn  # noqa: PLW0603

    if _compiled_graph is not None:
        return _compiled_graph

    settings = get_settings()
    raw_db = settings.database_url
    for prefix in ("sqlite+aiosqlite:///", "sqlite:///", "sqlite://", "sqlite:"):
        if raw_db.startswith(prefix):
            raw_db = raw_db[len(prefix):]
            break
    db_path = Path(raw_db if raw_db.startswith("/") else f"/{raw_db}")
    db_path.parent.mkdir(parents=True, exist_ok=True)

    _conn = await aiosqlite.connect(str(db_path))
    _saver = AsyncSqliteSaver(_conn)
    await _saver.setup()

    builder = _build_graph()
    _compiled_graph = builder.compile(
        checkpointer=_saver,
        interrupt_before=["human_review"],
    )
    log.info("LangGraph compiled and checkpoint saver initialised", db=str(db_path))
    return _compiled_graph


async def close_graph() -> None:
    """Close the underlying aiosqlite connection on shutdown."""
    global _conn, _compiled_graph, _saver  # noqa: PLW0603
    if _conn is not None:
        await _conn.close()
        _conn = None
    _saver = None
    _compiled_graph = None


# ── Streaming ─────────────────────────────────────────────────────────────────

async def stream_audit(
    thread_id: str,
    initial_state: AuditState,
) -> AsyncGenerator[SSEEvent, None]:
    """
    Run the audit graph and yield SSE events for every node transition.

    LangGraph's astream() yields one dict per completed node. We map each to
    a typed SSEEvent so the frontend can render the pipeline in real time.
    """
    graph = await get_graph()
    config = {"configurable": {"thread_id": thread_id}}

    logger = log.bind(thread_id=thread_id)
    logger.info("Audit stream started")

    state_dict = initial_state.model_dump(mode="json")

    try:
        async for chunk in graph.astream(state_dict, config=config):
            for node_name, node_output in chunk.items():
                if node_name == "__interrupt__":
                    yield SSEEvent(
                        event=SSEEventType.AWAITING_HUMAN,
                        thread_id=thread_id,
                        node=AgentNode.HUMAN_REVIEW,
                        data={"message": "Patch verified. Awaiting human approval."},
                    )
                    return

                state = AuditState.model_validate(node_output)
                yield _node_to_sse_event(node_name, state, thread_id)

                if state.status in (AuditStatus.FAILED, AuditStatus.COMPLETED):
                    yield SSEEvent(
                        event=SSEEventType.COMPLETED,
                        thread_id=thread_id,
                        data={"status": state.status.value, "error": state.error},
                    )
                    return

    except Exception as exc:
        logger.exception("Audit graph raised an unhandled exception", error=str(exc))
        yield SSEEvent(
            event=SSEEventType.ERROR,
            thread_id=thread_id,
            data={"error": str(exc)},
        )


def _node_to_sse_event(node_name: str, state: AuditState, thread_id: str) -> SSEEvent:
    """Map a completed graph node to the appropriate SSE event type."""
    if node_name == "scanner":
        findings_data = (
            [f.model_dump() for f in state.scanner_output.findings]
            if state.scanner_output
            else []
        )
        return SSEEvent(
            event=SSEEventType.NODE_COMPLETE,
            thread_id=thread_id,
            node=AgentNode.SCANNER,
            data={
                "findings": findings_data,
                "summary": state.scanner_output.summary if state.scanner_output else "",
                "risk_score": state.scanner_output.risk_score if state.scanner_output else 0,
            },
        )

    if node_name == "patcher":
        return SSEEvent(
            event=SSEEventType.PATCH_READY,
            thread_id=thread_id,
            node=AgentNode.PATCHER,
            data={
                "patch": state.patcher_output.diff.model_dump() if state.patcher_output else {},
                "rationale": state.patcher_output.rationale if state.patcher_output else "",
                "retry_count": state.patch_retry_count,
            },
        )

    if node_name == "critic":
        return SSEEvent(
            event=SSEEventType.CRITIC_VERDICT,
            thread_id=thread_id,
            node=AgentNode.CRITIC,
            data={
                "verdict": state.critic_output.verdict.value if state.critic_output else "unknown",
                "feedback": state.critic_output.feedback if state.critic_output else "",
                "syntax_valid": state.critic_output.syntax_valid if state.critic_output else False,
            },
        )

    return SSEEvent(
        event=SSEEventType.NODE_COMPLETE,
        thread_id=thread_id,
        data={"node": node_name, "status": state.status.value},
    )


# ── Human-in-the-loop resume ──────────────────────────────────────────────────

async def resume_after_approval(
    thread_id: str,
    decision: ApprovalDecision,
    comment: str | None,
) -> AuditState:
    """
    Resume a paused graph thread with the human's approval decision.

    LangGraph resumes from the checkpoint automatically when we call ainvoke
    with the same thread_id. We inject the decision into the state before
    resuming by updating the checkpoint directly.
    """
    graph = await get_graph()
    config = {"configurable": {"thread_id": thread_id}}

    # Read current checkpoint state
    checkpoint = await graph.aget_state(config)
    if checkpoint is None:
        raise ValueError(f"No checkpoint found for thread_id={thread_id!r}")

    current_state = AuditState.model_validate(checkpoint.values)
    if current_state.status != AuditStatus.AWAITING_APPROVAL:
        raise ValueError(
            f"Thread {thread_id!r} is not awaiting approval (status={current_state.status})"
        )

    # Inject the human decision into state before resuming
    updated_values = current_state.model_copy(
        update={"approval_decision": decision, "approval_comment": comment}
    ).model_dump(mode="json")

    await graph.aupdate_state(config, updated_values, as_node="human_review")

    # Resume graph execution (runs human_review node → END)
    final_output = await graph.ainvoke(None, config=config)
    return AuditState.model_validate(final_output)
