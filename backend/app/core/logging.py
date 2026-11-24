"""
Structured JSON logging via structlog.

We configure structlog once at application startup. Every module then calls
`structlog.get_logger()` and gets a pre-configured, bound logger.

Why structlog over stdlib logging?
- Native context binding (bind() carries fields across call frames)
- Renders as clean JSON in production, human-readable in dev terminal
- Zero-cost lazy evaluation of log arguments
"""

import logging
import sys

import structlog


def configure_logging(log_level: str = "INFO") -> None:
    """Wire structlog to the stdlib logging backend.

    Call this exactly once from main.py before the app starts accepting
    requests. Calling it multiple times is safe (idempotent processors).
    """
    shared_processors: list[structlog.types.Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
    ]

    structlog.configure(
        processors=[
            *shared_processors,
            # Pass through to stdlib so we can capture third-party logs too
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    # Render as JSON in production, pretty-print in dev
    renderer: structlog.types.Processor
    if sys.stdout.isatty():
        renderer = structlog.dev.ConsoleRenderer()
    else:
        renderer = structlog.processors.JSONRenderer()

    formatter = structlog.stdlib.ProcessorFormatter(
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            *shared_processors,
            renderer,
        ],
    )

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)

    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.addHandler(handler)
    root_logger.setLevel(log_level)

    # Quiet down noisy third-party libraries
    for noisy in ("httpx", "httpcore", "uvicorn.access"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
