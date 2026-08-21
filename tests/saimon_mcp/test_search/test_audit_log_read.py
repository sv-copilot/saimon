"""Tests for SAIMON-AUDIT-LOG-READ-1 — read-only audit_log MCP tool.

KPI measurement substrate: exposes audit_log via an auth-enforced, read-only
MCP tool so the Phase-2 measurement runner can compute KPIs
(verify.pass_rate, generate.grounded_rate) without raw DB access.

Covers:
- tool is registered in the /tools manifest
- auth is enforced (fail-closed)
- filters (service_name, event_type, payload_key, time range) are applied
- payload is preserved intact
- empty/fallback result shape
"""


class _FakePool:
    """In-memory DatabasePool double that records queries and returns rows."""

    def __init__(self, rows=None):
        self._rows = rows or []
        self.calls = []

    async def fetch(self, query, *args):
        self.calls.append((query, args))
        return self._rows


def _body(trace_id, **params):
    return {
        "trace_id": trace_id,
        "content_type": "search",
        "parameters": params,
    }


class TestAuditLogReadToolRegistered:
    def test_tool_in_manifest(self, client, auth_headers):
        """saimon_list_audit_log appears in the /tools listing."""
        response = client.get("/tools", headers=auth_headers)
        assert response.status_code == 200
        names = {t["name"] for t in response.json()["tools"]}
        assert "saimon_list_audit_log" in names


class TestAuditLogReadAuth:
    def test_rejects_missing_key(self, client, sample_trace_id):
        """401 without an API key."""
        response = client.post(
            "/tools/saimon_list_audit_log", json=_body(sample_trace_id)
        )
        assert response.status_code == 401

    def test_rejects_wrong_key(self, client, sample_trace_id):
        """401 with a wrong API key."""
        response = client.post(
            "/tools/saimon_list_audit_log",
            json=_body(sample_trace_id),
            headers={"X-Saimon-API-Key": "wrong-key"},
        )
        assert response.status_code == 401


class TestAuditLogReadFilters:
    def test_filters_are_applied_to_query(
        self, client, sample_trace_id, auth_headers, monkeypatch
    ):
        """service_name/event_type/payload_key/time filters map to WHERE clauses."""
        from saimon_mcp.search import server

        pool = _FakePool(rows=[])
        monkeypatch.setattr(server, "_db_pool", pool)

        response = client.post(
            "/tools/saimon_list_audit_log",
            json=_body(
                sample_trace_id,
                service_name="generate-mcp",
                event_type="response",
                payload_key="citations_count",
                created_after="2026-08-01T00:00:00Z",
                created_before="2026-08-31T00:00:00Z",
                limit=10,
            ),
            headers=auth_headers,
        )

        assert response.status_code == 200
        assert pool.calls, "expected a DB query to be issued"
        sql, args = pool.calls[0]
        assert "service_name = $1" in sql
        assert "event_type = $2" in sql
        assert "payload ? $3" in sql
        assert "created_at >= $4" in sql
        assert "created_at <= $5" in sql
        assert args == (
            "generate-mcp",
            "response",
            "citations_count",
            "2026-08-01T00:00:00Z",
            "2026-08-31T00:00:00Z",
            10,
        )

    def test_no_filters_issues_plain_query(
        self, client, sample_trace_id, auth_headers, monkeypatch
    ):
        """Without filters, only the LIMIT parameter is bound."""
        from saimon_mcp.search import server

        pool = _FakePool(rows=[])
        monkeypatch.setattr(server, "_db_pool", pool)

        client.post(
            "/tools/saimon_list_audit_log",
            json=_body(sample_trace_id),
            headers=auth_headers,
        )

        assert pool.calls
        sql, args = pool.calls[0]
        assert "WHERE" not in sql
        assert args == (50,)


class TestAuditLogReadPayload:
    def test_payload_preserved(self, client, sample_trace_id, auth_headers, monkeypatch):
        """Entries return payload (incl. citations_count) intact."""
        from saimon_mcp.search import server

        rows = [
            {
                "trace_id": sample_trace_id,
                "service_name": "generate-mcp",
                "event_type": "response",
                "payload": '{"status": "success", "citations_count": 3}',
                "created_at": "2026-08-21T00:00:00Z",
            }
        ]
        monkeypatch.setattr(server, "_db_pool", _FakePool(rows=rows))

        response = client.post(
            "/tools/saimon_list_audit_log",
            json=_body(sample_trace_id, limit=5),
            headers=auth_headers,
        )
        data = response.json()
        assert data["status"] == "success"
        assert data["data"]["total"] == 1
        entry = data["data"]["entries"][0]
        assert entry["service_name"] == "generate-mcp"
        assert entry["event_type"] == "response"
        assert entry["payload"] == '{"status": "success", "citations_count": 3}'


class TestAuditLogReadFallback:
    def test_empty_result_when_no_db(self, client, sample_trace_id, auth_headers):
        """Without a DB pool, returns degraded with an empty entries list."""
        response = client.post(
            "/tools/saimon_list_audit_log",
            json=_body(sample_trace_id),
            headers=auth_headers,
        )
        data = response.json()
        assert data["status"] == "degraded"
        assert data["data"]["entries"] == []
        assert data["data"]["total"] == 0
