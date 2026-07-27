"""Tests for research_shared.audit — structured logging with trace IDs."""

import io
import json
import uuid

from research_shared.audit import AuditLogger


class TestAuditLogger:
    def test_construction(self):
        """AuditLogger constructs with defaults."""
        logger = AuditLogger()
        assert logger.trace_id is None
        assert logger.service_name == "saimon"

    def test_construction_with_trace_id(self, sample_trace_id):
        """AuditLogger accepts an explicit trace_id."""
        logger = AuditLogger(trace_id=sample_trace_id)
        assert logger.trace_id == sample_trace_id

    def test_construction_with_service_name(self):
        """AuditLogger accepts a custom service name."""
        logger = AuditLogger(service_name="search-mcp")
        assert logger.service_name == "search-mcp"

    def test_with_trace_id_returns_new_instance(self, sample_trace_id):
        """with_trace_id creates a new logger with the given trace_id."""
        logger = AuditLogger()
        child = logger.with_trace_id(sample_trace_id)
        assert child is not logger
        assert child.trace_id == sample_trace_id
        assert logger.trace_id is None  # original unchanged

    def test_log_info_writes_structured(self):
        """log writes structured JSON with metadata."""
        buf = io.StringIO()
        logger = AuditLogger(trace_id=str(uuid.uuid4()), output=buf)

        logger.info("request_started", content_type="blog_post")
        output = buf.getvalue()

        record = json.loads(output)
        assert record["event"] == "request_started"
        assert record["level"] == "info"
        assert record["content_type"] == "blog_post"
        assert "trace_id" in record
        assert "timestamp" in record

    def test_log_error_writes_with_exception(self):
        """error level includes exception info when provided."""
        buf = io.StringIO()
        logger = AuditLogger(trace_id=str(uuid.uuid4()), output=buf)

        try:
            raise ValueError("test error")
        except ValueError as exc:
            logger.error("llm_call_failed", exc_info=exc)

        output = buf.getvalue()
        record = json.loads(output)
        assert record["level"] == "error"
        assert record["event"] == "llm_call_failed"
        assert record["exception_type"] == "ValueError"
        assert "test error" in record["exception_message"]

    def test_log_warning(self):
        """warning level works."""
        buf = io.StringIO()
        logger = AuditLogger(trace_id=str(uuid.uuid4()), output=buf)

        logger.warning("rate_limit_nearing", remaining=5)
        record = json.loads(buf.getvalue())
        assert record["level"] == "warning"
        assert record["remaining"] == 5

    def test_log_debug(self):
        """debug level works."""
        buf = io.StringIO()
        logger = AuditLogger(trace_id=str(uuid.uuid4()), output=buf)

        logger.debug("db_query", query="SELECT 1", duration_ms=2.3)
        record = json.loads(buf.getvalue())
        assert record["level"] == "debug"
        assert record["duration_ms"] == 2.3

    def test_request_response_logging(self):
        """log_request and log_response convenience methods."""
        buf = io.StringIO()
        tid = str(uuid.uuid4())
        logger = AuditLogger(trace_id=tid, output=buf)

        logger.log_request(content_type="blog_post", sources_count=3)
        logger.log_response(status="success", citations_count=2)

        lines = buf.getvalue().strip().split("\n")
        req = json.loads(lines[0])
        resp = json.loads(lines[1])

        assert req["event"] == "request"
        assert req["content_type"] == "blog_post"
        assert req["sources_count"] == 3

        assert resp["event"] == "response"
        assert resp["status"] == "success"
        assert resp["citations_count"] == 2

    def test_missing_trace_id_warns(self):
        """Logging without trace_id still works (dev convenience)."""
        buf = io.StringIO()
        logger = AuditLogger(output=buf)
        logger.info("no_trace_test")
        record = json.loads(buf.getvalue())
        assert record["event"] == "no_trace_test"
