import structlog
import uuid

structlog.configure(
    processors=[
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.dev.ConsoleRenderer()
    ],
    context_class=dict,
    logger_factory=structlog.PrintLoggerFactory(),
    cache_logger_on_first_use=True,
)


def new_ref() -> str:
    return str(uuid.uuid4())


def bind_ref(logger: structlog.BoundLogger, ref: str) -> structlog.BoundLogger:
    return logger.bind(ref=ref)
