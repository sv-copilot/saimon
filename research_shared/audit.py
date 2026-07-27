"""audit.py — structured logging with trace-ID propagation.

Every MCP uses AuditLogger to emit JSON-line structured logs that carry
the trace_id across the request lifecycle.  This enables end-to-end
observability without an external tracing service.
"""

from __future__ import annotations

import json
import time
from typing import Any, TextIO


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
    ) -> None:
        self.trace_id = trace_id
        self.service_name = service_name
        self._output = output

    # ------------------------------------------------------------------
    # builder
    # ------------------------------------------------------------------

    def with_trace_id(self, trace_id: str) -> AuditLogger:
        """Return a new AuditLogger with the given trace_id."""
        return AuditLogger(
            trace_id=trace_id,
            service_name=self.service_name,
            output=self._output,
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

        line = json.dumps(record, default=str)
        if self._output is not None:
            self._output.write(line + "\n")
        else:
            print(line)

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
