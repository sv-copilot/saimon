"""audit.py — structured logging with trace-ID propagation.

Every MCP uses AuditLogger to emit JSON-line structured logs that carry
the trace_id across the request lifecycle.  This enables end-to-end
observability without an external tracing service.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any, TextIO

_log = logging.getLogger("saimon.audit")

# Module-level DB pool for audit writes — set via set_audit_db_pool()
_audit_db_pool: Any = None


def set_audit_db_pool(pool: Any | None) -> None:
    """Inject a DatabasePool for writing audit entries to the audit_log table."""
    global _audit_db_pool
    _audit_db_pool = pool


class AuditLogger:
    """Structured JSON-line logger with mandatory trace_id support.

    Usage::

        logger = AuditLogger(trace_id=request.trace_id)
        logger.info("request_started", content_type="blog_post")
        logger.log_request(...)
        # ... do work ...
        logger.log_response(status="success", citations_count=3)

    Output goes to *output* (defaults to an in-memory buffer for testing).
    In production, wire to stderr or a file.
    """

    def __init__(
        self,
        trace_id: str | None = None,
        service_name: str = "saimon",
        output: TextIO | None = None,
        caller_key_hash: str | None = None,
    ) -> None:
        self.trace_id = trace_id
        self.service_name = service_name
        self._output = output
        self.caller_key_hash = caller_key_hash

    # ------------------------------------------------------------------
    # builder
    # ------------------------------------------------------------------

    def with_trace_id(self, trace_id: str) -> AuditLogger:
        """Return a new AuditLogger with the given trace_id."""
        return AuditLogger(
            trace_id=trace_id,
            service_name=self.service_name,
            output=self._output,
            caller_key_hash=self.caller_key_hash,
        )

    # ------------------------------------------------------------------
    # core log method
    # ------------------------------------------------------------------

    def _emit(self, level: str, event: str, **kwargs: Any) -> None:
        record: dict[str, Any] = {
            "timestamp": time.time(),
            "level": level,
            "event": event,
            "service": self.service_name,
            **kwargs,
        }
        if self.trace_id:
            record["trace_id"] = self.trace_id
        if self.caller_key_hash:
            record["caller_key_hash"] = self.caller_key_hash

        line = json.dumps(record, default=str)
        if self._output is not None:
            self._output.write(line + "\n")
        else:
            print(line)

        # ── also write to audit_log table if DB is connected ──
        if _audit_db_pool is not None and self.trace_id:
            self._schedule_db_write(record)

    def _schedule_db_write(self, record: dict[str, Any]) -> None:
        """Write an audit entry to the audit_log table (fire-and-forget)."""
        import asyncio

        async def _write():
            try:
                await _audit_db_pool.execute(
                    "INSERT INTO audit_log (trace_id, service_name, event_type, payload) "
                    "VALUES ($1, $2, $3, $4)",
                    record.get("trace_id", "unknown"),
                    self.service_name,
                    record.get("event", "unknown"),
                    json.dumps(record, default=str),
                )
            except Exception:  # noqa: BLE001 — audit write must never crash
                pass

        try:
            loop = asyncio.get_running_loop()
            loop.create_task(_write())
        except RuntimeError:
            # No running event loop — skip DB write
            pass

    def debug(self, event: str, **kwargs: Any) -> None:
        self._emit("debug", event, **kwargs)

    def info(self, event: str, **kwargs: Any) -> None:
        self._emit("info", event, **kwargs)

    def warning(self, event: str, **kwargs: Any) -> None:
        self._emit("warning", event, **kwargs)

    def error(
        self, event: str, exc_info: BaseException | None = None, **kwargs: Any
    ) -> None:
        if exc_info is not None:
            kwargs.setdefault("exception_type", type(exc_info).__name__)
            kwargs.setdefault("exception_message", str(exc_info))
        self._emit("error", event, **kwargs)

    # ------------------------------------------------------------------
    # convenience helpers
    # ------------------------------------------------------------------

    def log_request(
        self,
        content_type: str,
        sources_count: int = 0,
        **kwargs: Any,
    ) -> None:
        """Log an inbound request."""
        self.info(
            "request",
            content_type=content_type,
            sources_count=sources_count,
            **kwargs,
        )

    def log_response(
        self,
        status: str,
        citations_count: int = 0,
        **kwargs: Any,
    ) -> None:
        """Log an outbound response."""
        self.info(
            "response",
            status=status,
            citations_count=citations_count,
            **kwargs,
        )
