"""Tests for health monitor — aggregation + quality metrics (#47)."""



# ---------------------------------------------------------------------------
# Health aggregate endpoint
# ---------------------------------------------------------------------------

class TestHealthAggregate:
    def test_aggregate_returns_200(self, client):
        """GET /health/aggregate returns 200 and valid JSON."""
        response = client.get("/health/aggregate")
        assert response.status_code == 200
        data = response.json()
        assert "status" in data
        assert "services" in data
        assert "summary" in data

    def test_aggregate_has_all_expected_service_names(self, client):
        """Aggregate response includes keys for all 6 MCPs."""
        response = client.get("/health/aggregate")
        data = response.json()
        services = data["services"]
        expected = {"search", "generate", "export", "evaluate", "verify", "explore", "crew"}
        assert set(services.keys()) == expected

    def test_aggregate_overall_status_is_valid(self, client):
        """Overall status is one of ok/degraded/down."""
        response = client.get("/health/aggregate")
        data = response.json()
        assert data["status"] in ("ok", "degraded", "down")

    def test_aggregate_summary_matches_services_count(self, client):
        """Summary string reports N/M services healthy."""
        response = client.get("/health/aggregate")
        data = response.json()
        assert "services healthy" in data["summary"]

    def test_each_service_has_required_fields(self, client):
        """Each service result has status and latency_ms."""
        response = client.get("/health/aggregate")
        data = response.json()
        for name, svc in data["services"].items():
            assert "status" in svc, f"{name} missing status"
            assert "latency_ms" in svc, f"{name} missing latency_ms"

    def test_aggregate_includes_quality_metrics(self, client):
        """Aggregate response includes quality metrics snapshot."""
        response = client.get("/health/aggregate")
        data = response.json()
        assert "quality" in data
        quality = data["quality"]
        assert "total_generations" in quality
        assert "ai_detect_pass_rate" in quality
        assert "avg_retries" in quality

    def test_aggregate_no_auth_required(self, client):
        """Aggregate does not require auth."""
        response = client.get("/health/aggregate")
        assert response.status_code == 200


# ---------------------------------------------------------------------------
# Quality metrics in /health
# ---------------------------------------------------------------------------

class TestQualityMetricsInHealth:
    def test_health_includes_quality_section(self, client):
        """GET /health includes quality metrics."""
        response = client.get("/health")
        data = response.json()
        checks = data.get("checks", {})
        assert "quality" in checks

    def test_quality_has_total_generations(self, client):
        """Quality section has total_generations."""
        response = client.get("/health")
        data = response.json()
        quality = data["checks"]["quality"]
        assert isinstance(quality["total_generations"], int)
        assert quality["total_generations"] >= 0

    def test_quality_has_ai_detect_pass_rate(self, client):
        """Quality section has ai_detect_pass_rate (0.0–1.0)."""
        response = client.get("/health")
        data = response.json()
        quality = data["checks"]["quality"]
        assert 0.0 <= quality["ai_detect_pass_rate"] <= 1.0

    def test_quality_has_avg_retries(self, client):
        """Quality section has avg_retries."""
        response = client.get("/health")
        data = response.json()
        quality = data["checks"]["quality"]
        assert isinstance(quality["avg_retries"], (int, float))
        assert quality["avg_retries"] >= 0

    def test_quality_has_content_type_counts(self, client):
        """Quality section has content_type_counts dict."""
        response = client.get("/health")
        data = response.json()
        quality = data["checks"]["quality"]
        assert isinstance(quality["content_type_counts"], dict)

    def test_quality_has_llm_consecutive_failures(self, client):
        """Quality section has llm_consecutive_failures."""
        response = client.get("/health")
        data = response.json()
        quality = data["checks"]["quality"]
        assert isinstance(quality["llm_consecutive_failures"], int)
        assert quality["llm_consecutive_failures"] >= 0


# ---------------------------------------------------------------------------
# Quality metrics functions
# ---------------------------------------------------------------------------

class TestRecordGenerationMetrics:
    def test_record_increments_total(self):
        """_record_generation_metrics increments total_generations."""
        from mcp.generate.server import (
            _quality_metrics,
            _record_generation_metrics,
        )

        before = _quality_metrics["total_generations"]
        _record_generation_metrics("blog_post")
        assert _quality_metrics["total_generations"] == before + 1

    def test_record_tracks_content_type(self):
        """_record_generation_metrics tracks content type counts."""
        from mcp.generate.server import (
            _quality_metrics,
            _record_generation_metrics,
        )

        _record_generation_metrics("blog_post")
        counts = _quality_metrics.setdefault("content_type_counts", {})
        assert counts.get("blog_post", 0) >= 1

    def test_record_with_iteration_log_tracks_retries(self):
        """_record_generation_metrics tracks retries from iteration log."""
        from mcp.generate.server import (
            _quality_metrics,
            _record_generation_metrics,
        )

        before_retries = _quality_metrics["total_retries"]
        # 3 attempts = 2 retries
        log = [
            {"attempt": 1, "score": 0.2, "justification": "fail"},
            {"attempt": 2, "score": 0.3, "justification": "fail"},
            {"attempt": 3, "score": 0.6, "justification": "pass"},
        ]
        _record_generation_metrics("research_note", log)
        assert _quality_metrics["total_retries"] == before_retries + 2

    def test_record_with_passing_log_counts_pass(self):
        """_record_generation_metrics counts AI detect passes."""
        from mcp.generate.server import (
            _quality_metrics,
            _record_generation_metrics,
        )

        before_passes = _quality_metrics["ai_detect_passes"]
        log = [{"attempt": 1, "score": 0.8, "justification": "pass"}]
        _record_generation_metrics("summary", log)
        assert _quality_metrics["ai_detect_passes"] == before_passes + 1

    def test_record_resets_llm_failures_on_success(self):
        """_record_generation_metrics resets llm_consecutive_failures."""
        from mcp.generate.server import (
            _quality_metrics,
            _record_generation_metrics,
            _record_llm_failure,
        )

        _record_llm_failure()
        _record_llm_failure()
        assert _quality_metrics["llm_consecutive_failures"] == 2
        _record_generation_metrics("blog_post")
        assert _quality_metrics["llm_consecutive_failures"] == 0


class TestRecordLLMFailure:
    def test_record_llm_failure_increments_counter(self):
        """_record_llm_failure increments consecutive failures."""
        from mcp.generate.server import (
            _quality_metrics,
            _record_llm_failure,
        )

        before = _quality_metrics["llm_consecutive_failures"]
        _record_llm_failure()
        assert _quality_metrics["llm_consecutive_failures"] == before + 1

    def test_record_llm_failure_sets_timestamp(self):
        """_record_llm_failure sets last_llm_failure_at."""
        from mcp.generate.server import (
            _quality_metrics,
            _record_llm_failure,
        )

        _record_llm_failure()
        assert _quality_metrics["last_llm_failure_at"] is not None


class TestGetQualitySummary:
    def test_summary_handles_zero_generations(self):
        """_get_quality_summary handles division by zero gracefully."""
        from mcp.generate.server import (
            _get_quality_summary,
            _quality_metrics,
        )

        _quality_metrics["total_generations"] = 0
        summary = _get_quality_summary()
        assert summary["total_generations"] == 0
        assert isinstance(summary["ai_detect_pass_rate"], float)
        assert isinstance(summary["avg_retries"], float)
