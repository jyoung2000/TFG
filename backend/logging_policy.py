"""Centralized logging policy for request and background exception paths,
plus secret redaction for every log record and error body."""

from __future__ import annotations

import logging
import re

from fastapi import Request

from _routes._errors import HTTPError

logger = logging.getLogger(__name__)

# Provider key shapes we know, plus generic bearer/basic credentials. Applied
# to log messages *and* to error bodies returned to the renderer.
_SECRET_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"sk-or-v1-[A-Za-z0-9]{8,}"),  # OpenRouter
    re.compile(r"sk-(?:proj-|ant-)?[A-Za-z0-9_-]{16,}"),  # OpenAI-style
    re.compile(r"AIza[0-9A-Za-z_-]{20,}"),  # Google API keys
    re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._~+/=-]{12,}"),
    re.compile(r"(?i)(basic\s+)[A-Za-z0-9+/=]{12,}"),
    re.compile(r"(?i)((?:api[_-]?key|token|secret)\s*[=:]\s*)[\"']?[A-Za-z0-9._~+/-]{12,}"),
)


def redact_secrets(text: str) -> str:
    """Replace anything that looks like a credential with a marker."""
    if not text:
        return text
    redacted = text
    for pattern in _SECRET_PATTERNS:
        if pattern.groups:
            redacted = pattern.sub(lambda m: f"{m.group(1)}[REDACTED]", redacted)
        else:
            redacted = pattern.sub("[REDACTED]", redacted)
    return redacted


class SecretRedactingFilter(logging.Filter):
    """Logging filter that redacts secrets from the formatted message and args."""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            message = record.getMessage()
        except Exception:  # noqa: BLE001 - never let logging crash the app
            return True
        redacted = redact_secrets(message)
        if redacted != message:
            record.msg = redacted
            record.args = ()
        return True


def install_secret_redaction() -> None:
    """Attach the redaction filter to the root logger's handlers (idempotent)."""
    root = logging.getLogger()
    for handler in root.handlers:
        if not any(isinstance(f, SecretRedactingFilter) for f in handler.filters):
            handler.addFilter(SecretRedactingFilter())
    if not any(isinstance(f, SecretRedactingFilter) for f in root.filters):
        root.addFilter(SecretRedactingFilter())


def log_http_error(request: Request, exc: HTTPError) -> None:
    """Log typed HTTP errors with policy-based traceback behavior."""
    detail = redact_secrets(str(exc.detail))
    if 500 <= exc.status_code <= 599:
        logger.error(
            "HTTP error on %s %s: [%s] %s",
            request.method,
            request.url.path,
            exc.status_code,
            detail,
            exc_info=(type(exc), exc, exc.__traceback__),
        )
        return

    logger.warning(
        "HTTP error on %s %s: [%s] %s",
        request.method,
        request.url.path,
        exc.status_code,
        detail,
    )


def log_unhandled_exception(request: Request, exc: Exception) -> None:
    """Log unhandled request exceptions with full traceback."""
    logger.error(
        "Unhandled error on %s %s",
        request.method,
        request.url.path,
        exc_info=(type(exc), exc, exc.__traceback__),
    )


def log_background_exception(task_name: str, exc: Exception) -> None:
    """Log unhandled background task exceptions with full traceback."""
    logger.error(
        "Unhandled background error in task '%s'",
        task_name,
        exc_info=(type(exc), exc, exc.__traceback__),
    )
