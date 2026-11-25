"""
Audit router – all /api/v1/audit endpoints.

Endpoint summary:
  POST   /start          – Start a new audit (snippet or file upload)
  GET    /{thread_id}/stream   – SSE stream of live agent events
  POST   /{thread_id}/approve  – Resume a paused thread with human decision
  GET    /{thread_id}          – Get current audit state summary
"""

from __future__ import annotations

import json
import uuid
from collections.abc import AsyncGenerator
from typing import Annotated

import structlog
from fastapi import APIRouter, File, HTTPException, Query, UploadFile, status
from fastapi.responses import StreamingResponse

from app.graph.audit_graph import resume_after_approval, stream_audit
from app.schemas.audit import (
    ApprovalRequest,
    AuditStartRequest,
    AuditStartResponse,
    AuditState,
    AuditStatus,
    AuditSummaryResponse,
    SSEEvent,
    SSEEventType,
)

log = structlog.get_logger(__name__)
router = APIRouter(prefix="/api/v1/audit", tags=["audit"])


# ── POST /start ───────────────────────────────────────────────────────────────

@router.post("/start", response_model=AuditStartResponse, status_code=status.HTTP_202_ACCEPTED)
async def start_audit_snippet(body: AuditStartRequest) -> AuditStartResponse:
    """
    Start a new audit from a raw code snippet in the JSON body.
    Returns immediately with a thread_id; use /stream to follow progress.
    """
    thread_id = str(uuid.uuid4())
    log.info("Audit started via snippet", thread_id=thread_id, filename=body.filename)
    return AuditStartResponse(
        thread_id=thread_id,
        status=AuditStatus.PENDING,
        message=f"Audit initiated. Stream progress at /api/v1/audit/{thread_id}/stream",
    )


@router.post(
    "/start/upload",
    response_model=AuditStartResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def start_audit_upload(
    file: Annotated[UploadFile, File(description="Python/JS/TS file or ZIP archive")],
) -> AuditStartResponse:
    """Start a new audit from a file or ZIP archive upload."""
    thread_id = str(uuid.uuid4())
    log.info("Audit started via upload", thread_id=thread_id, filename=file.filename)
    return AuditStartResponse(
        thread_id=thread_id,
        status=AuditStatus.PENDING,
        message=f"Upload received. Stream progress at /api/v1/audit/{thread_id}/stream",
    )


# ── GET /{thread_id}/stream ───────────────────────────────────────────────────

@router.get("/{thread_id}/stream")
async def stream_audit_events(
    thread_id: str,
    source_code: Annotated[str | None, Query()] = None,
    filename: Annotated[str, Query()] = "snippet.py",
    language: Annotated[str, Query()] = "python",
) -> StreamingResponse:
    """
    SSE endpoint – streams live agent events as the graph executes.

    The source_code query param is used when triggered from the snippet flow.
    For file uploads, the client should send the content as base64 or use the
    separate upload endpoint. This design keeps the SSE connection stateless
    on the HTTP layer (no session needed).
    """
    if not source_code:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="source_code query parameter is required for streaming",
        )

    initial_state = AuditState(
        thread_id=thread_id,
        source_code=source_code,
        filename=filename,
        language=language,
        status=AuditStatus.PENDING,
    )

    async def event_generator() -> AsyncGenerator[str, None]:
        try:
            async for event in stream_audit(thread_id, initial_state):
                yield _format_sse(event)
        except Exception as exc:
            log.exception("SSE stream error", thread_id=thread_id, error=str(exc))
            error_event = SSEEvent(
                event=SSEEventType.ERROR,
                thread_id=thread_id,
                data={"error": str(exc)},
            )
            yield _format_sse(error_event)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",  # Disable Nginx buffering for SSE
            "Connection": "keep-alive",
        },
    )


# ── POST /{thread_id}/approve ─────────────────────────────────────────────────

@router.post("/{thread_id}/approve", response_model=AuditSummaryResponse)
async def approve_patch(thread_id: str, body: ApprovalRequest) -> AuditSummaryResponse:
    """
    Resume a paused LangGraph thread after human review.

    The graph must be in AWAITING_APPROVAL status. If the thread doesn't exist
    or is in the wrong state, we return 404/409 respectively.
    """
    log.info(
        "Human approval received",
        thread_id=thread_id,
        decision=body.decision,
        comment=body.comment,
    )
    try:
        final_state = await resume_after_approval(
            thread_id=thread_id,
            decision=body.decision,
            comment=body.comment,
        )
    except ValueError as exc:
        error_msg = str(exc)
        if "No checkpoint" in error_msg:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=error_msg) from exc
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=error_msg) from exc

    return _state_to_summary(final_state)


# ── GET /{thread_id} ──────────────────────────────────────────────────────────

@router.get("/{thread_id}", response_model=AuditSummaryResponse)
async def get_audit_state(thread_id: str) -> AuditSummaryResponse:
    """
    Fetch the latest persisted state for a given thread.

    Useful for polling or reconnecting after an SSE disconnect.
    """
    from app.graph.audit_graph import get_graph

    graph = await get_graph()
    config = {"configurable": {"thread_id": thread_id}}
    checkpoint = await graph.aget_state(config)

    if checkpoint is None or not checkpoint.values:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No audit found for thread_id={thread_id!r}",
        )

    state = AuditState.model_validate(checkpoint.values)
    return _state_to_summary(state)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _format_sse(event: SSEEvent) -> str:
    """
    Format an SSEEvent as a proper SSE wire frame.
    The 'data:' line must be a single JSON string; the blank line terminates the event.
    """
    payload = json.dumps(event.model_dump(mode="json"), default=str)
    return f"event: {event.event.value}\ndata: {payload}\n\n"


def _state_to_summary(state: AuditState) -> AuditSummaryResponse:
    return AuditSummaryResponse(
        thread_id=state.thread_id,
        status=state.status,
        scanner_output=state.scanner_output,
        patcher_output=state.patcher_output,
        critic_output=state.critic_output,
        patch_retry_count=state.patch_retry_count,
        error=state.error,
        created_at=state.created_at,
        updated_at=state.updated_at,
    )
