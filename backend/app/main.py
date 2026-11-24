"""
FastAPI application entry point.

Intentionally thin – all business logic lives in routers, graph, and services.
This file owns: lifespan (startup/shutdown), middleware, and global exception handlers.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncGenerator

import structlog
import uvicorn
from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.core.config import get_settings
from app.core.logging import configure_logging
from app.graph.audit_graph import close_graph, get_graph
from app.routers.audit import router as audit_router

settings = get_settings()
configure_logging(settings.log_level)
log = structlog.get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """
    Eagerly initialise the LangGraph compiled graph at startup so the first
    request doesn't pay the compilation + SQLite connection cost.
    """
    log.info("HuGuard AI starting up", model=settings.ollama_model)
    await get_graph()
    log.info("LangGraph ready")
    yield
    await close_graph()
    log.info("HuGuard AI shutting down")


app = FastAPI(
    title="HuGuard AI",
    description="Autonomous Multi-Agent Codebase & Security Auditor",
    version="1.0.0",
    lifespan=lifespan,
    # Disable the default /docs redirect so we can control the OpenAPI path
    docs_url="/docs",
    redoc_url="/redoc",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(audit_router)


@app.get("/health", include_in_schema=False)
async def health_check() -> dict[str, str]:
    return {"status": "ok", "version": "1.0.0"}


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    log.exception("Unhandled exception", path=request.url.path, error=str(exc))
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"detail": "An internal error occurred. Check server logs."},
    )


if __name__ == "__main__":
    uvicorn.run(
        "app.main:app",
        host=settings.api_host,
        port=settings.api_port,
        reload=False,
        log_config=None,  # Suppress uvicorn's default logging; structlog handles it
    )
