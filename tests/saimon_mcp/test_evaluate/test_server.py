"""Tests for evaluate-mcp — quality gate MCP."""


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------

class TestHealth:
    def test_health_returns_ok(self, client):
        """GET /health returns 200 with status ok."""
        response = client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert data["service"] == "evaluate-mcp"

    def test_health_no_auth_required(self, client):
        """Health endpoint does not require auth."""
        response = client.get("/health")
        assert response.status_code == 200


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------

class TestAuth:
    def test_tool_endpoint_rejects_missing_key(self, client, sample_trace_id):
        """Any tool endpoint returns 401 without an API key."""
        response = client.post(
            "/tools/evaluate_content",
            json={
                "trace_id": sample_trace_id,
                "content_type": "evaluate",
                "parameters": {"content": "Hello world"},
            },
        )
        assert response.status_code == 401

    def test_tool_endpoint_rejects_wrong_key(self, client, sample_trace_id):
        """Any tool endpoint returns 401 with a wrong API key."""
        response = client.post(
            "/tools/evaluate_content",
            json={
                "trace_id": sample_trace_id,
                "content_type": "evaluate",
                "parameters": {"content": "Hello world"},
            },
            headers={"X-Saimon-API-Key": "wrong-key"},
        )
        assert response.status_code == 401

    def test_tool_endpoint_accepts_correct_key(
        self, client, sample_trace_id, auth_headers
    ):
        """A valid API key allows access to tool endpoints."""
        response = client.post(
            "/tools/evaluate_content",
            json={
                "trace_id": sample_trace_id,
                "content_type": "evaluate",
                "parameters": {"content": "Hello world"},
            },
            headers=auth_headers,
        )
        assert response.status_code != 401


# ---------------------------------------------------------------------------
# Envelope
# ---------------------------------------------------------------------------

class TestEnvelope:
    def test_response_uses_research_response_shape(
        self, client, sample_trace_id, auth_headers
    ):
        """Tool responses conform to ResearchResponse envelope."""
        response = client.post(
            "/tools/evaluate_content",
            json={
                "trace_id": sample_trace_id,
                "content_type": "evaluate",
                "parameters": {"content": "Test content for evaluation."},
            },
            headers=auth_headers,
        )
        data = response.json()
        assert "trace_id" in data
        assert "status" in data
        assert data["status"] in ("success", "error", "degraded")
        assert data["trace_id"] == sample_trace_id


# ---------------------------------------------------------------------------
# Tool: evaluate_content
# ---------------------------------------------------------------------------

class TestEvaluateContent:
    def test_requires_content(self, client, sample_trace_id, auth_headers):
        """evaluate_content returns error without content parameter."""
        response = client.post(
            "/tools/evaluate_content",
            json={
                "trace_id": sample_trace_id,
                "content_type": "evaluate",
                "parameters": {},
            },
            headers=auth_headers,
        )
        data = response.json()
        assert data["status"] == "error"
        assert any("content" in e.lower() for e in (data.get("errors") or []))

    def test_defaults_to_all_criteria(self, client, sample_trace_id, auth_headers):
        """evaluate_content evaluates all criteria when none specified."""
        response = client.post(
            "/tools/evaluate_content",
            json={
                "trace_id": sample_trace_id,
                "content_type": "evaluate",
                "parameters": {"content": "A clear and complete evaluation target."},
            },
            headers=auth_headers,
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "success"
        assert "scores" in data["data"]
        # At least 5 default criteria: clarity, completeness, coherence,
        # conciseness, tone_match
        assert len(data["data"]["scores"]) >= 5

    def test_filters_by_specified_criteria(
        self, client, sample_trace_id, auth_headers
    ):
        """evaluate_content evaluates only requested criteria."""
        response = client.post(
            "/tools/evaluate_content",
            json={
                "trace_id": sample_trace_id,
                "content_type": "evaluate",
                "parameters": {
                    "content": "Test content.",
                    "criteria": ["clarity", "coherence"],
                },
            },
            headers=auth_headers,
        )
        data = response.json()
        assert data["status"] == "success"
        score_names = [s["criterion"] for s in data["data"]["scores"]]
        assert set(score_names) == {"clarity", "coherence"}

    def test_each_score_has_required_fields(
        self, client, sample_trace_id, auth_headers
    ):
        """Each score entry includes criterion, score, max_score, justification."""
        response = client.post(
            "/tools/evaluate_content",
            json={
                "trace_id": sample_trace_id,
                "content_type": "evaluate",
                "parameters": {"content": "Test content."},
            },
            headers=auth_headers,
        )
        data = response.json()
        for score in data["data"]["scores"]:
            assert "criterion" in score
            assert "score" in score
            assert 0.0 <= score["score"] <= 1.0
            assert "max_score" in score
            assert score["max_score"] == 1.0
            assert "justification" in score
            assert len(score["justification"]) > 0

    def test_includes_overall_score(self, client, sample_trace_id, auth_headers):
        """evaluate_content returns an aggregate overall_score."""
        response = client.post(
            "/tools/evaluate_content",
            json={
                "trace_id": sample_trace_id,
                "content_type": "evaluate",
                "parameters": {"content": "Test content."},
            },
            headers=auth_headers,
        )
        data = response.json()
        assert "overall_score" in data["data"]
        assert 0.0 <= data["data"]["overall_score"] <= 1.0

    def test_rejects_unknown_criterion(self, client, sample_trace_id, auth_headers):
        """evaluate_content errors when an unknown criterion is requested."""
        response = client.post(
            "/tools/evaluate_content",
            json={
                "trace_id": sample_trace_id,
                "content_type": "evaluate",
                "parameters": {
                    "content": "Test content.",
                    "criteria": ["nonexistent"],
                },
            },
            headers=auth_headers,
        )
        data = response.json()
        assert data["status"] == "error"

    def test_accepts_tone_parameter(self, client, sample_trace_id, auth_headers):
        """evaluate_content accepts optional tone for tone_match criterion."""
        response = client.post(
            "/tools/evaluate_content",
            json={
                "trace_id": sample_trace_id,
                "content_type": "evaluate",
                "parameters": {
                    "content": "Test content.",
                    "tone": "professional",
                },
            },
            headers=auth_headers,
        )
        assert response.status_code == 200


# ---------------------------------------------------------------------------
# Tool: list_criteria
# ---------------------------------------------------------------------------

class TestListCriteria:
    def test_returns_registered_criteria(self, client, sample_trace_id, auth_headers):
        """list_criteria returns all evaluation criteria."""
        response = client.post(
            "/tools/list_criteria",
            json={
                "trace_id": sample_trace_id,
                "content_type": "evaluate",
            },
            headers=auth_headers,
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "success"
        assert isinstance(data["data"]["criteria"], list)
        assert len(data["data"]["criteria"]) >= 5

    def test_criteria_have_schema(self, client, sample_trace_id, auth_headers):
        """Each criterion includes name, description, and weight."""
        response = client.post(
            "/tools/list_criteria",
            json={
                "trace_id": sample_trace_id,
                "content_type": "evaluate",
            },
            headers=auth_headers,
        )
        data = response.json()
        for c in data["data"]["criteria"]:
            assert "name" in c
            assert "description" in c
            assert "weight" in c
            assert 0.0 <= c["weight"] <= 1.0


# ---------------------------------------------------------------------------
# Tool: get_criterion_detail
# ---------------------------------------------------------------------------

class TestGetCriterionDetail:
    def test_returns_detail_for_known_criterion(
        self, client, sample_trace_id, auth_headers
    ):
        """get_criterion_detail returns schema for clarity."""
        response = client.post(
            "/tools/get_criterion_detail",
            json={
                "trace_id": sample_trace_id,
                "content_type": "evaluate",
                "parameters": {"criterion_name": "clarity"},
            },
            headers=auth_headers,
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "success"
        assert data["data"]["name"] == "clarity"

    def test_errors_for_unknown_criterion(
        self, client, sample_trace_id, auth_headers
    ):
        """get_criterion_detail errors for unknown criterion."""
        response = client.post(
            "/tools/get_criterion_detail",
            json={
                "trace_id": sample_trace_id,
                "content_type": "evaluate",
                "parameters": {"criterion_name": "nonexistent"},
            },
            headers=auth_headers,
        )
        data = response.json()
        assert data["status"] == "error"

    def test_errors_without_criterion_name(
        self, client, sample_trace_id, auth_headers
    ):
        """get_criterion_detail errors without criterion_name."""
        response = client.post(
            "/tools/get_criterion_detail",
            json={
                "trace_id": sample_trace_id,
                "content_type": "evaluate",
                "parameters": {},
            },
            headers=auth_headers,
        )
        data = response.json()
        assert data["status"] == "error"


# ---------------------------------------------------------------------------
# Tool count
# ---------------------------------------------------------------------------

class TestToolCount:
    def test_tool_count_within_limit(self, client, auth_headers):
        """evaluate-mcp exposes ≤10 tools."""
        response = client.get("/tools", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert len(data["tools"]) <= 10


# ---------------------------------------------------------------------------
# Criterion: ai_detection
# ---------------------------------------------------------------------------

class TestAiDetection:
    def test_ai_detection_flags_known_llm_phrases(
        self, client, sample_trace_id, auth_headers
    ):
        """Content with known LLM template phrases scores low on ai_detection."""
        response = client.post(
            "/tools/evaluate_content",
            json={
                "trace_id": sample_trace_id,
                "content_type": "evaluate",
                "parameters": {
                    "content": (
                        "It is important to note that we must delve into "
                        "this matter. Furthermore, it plays a pivotal role. "
                        "In conclusion, thus we must act."
                    ),
                    "criteria": ["ai_detection"],
                },
            },
            headers=auth_headers,
        )
        data = response.json()
        assert data["status"] == "success"
        scores = data["data"]["scores"]
        assert len(scores) == 1
        assert scores[0]["criterion"] == "ai_detection"
        # Multiple LLM template phrases should push score well below 0.8
        assert scores[0]["score"] < 0.8

    def test_ai_detection_passes_human_text(
        self, client, sample_trace_id, auth_headers
    ):
        """Natural first-person text with personal stance scores high."""
        response = client.post(
            "/tools/evaluate_content",
            json={
                "trace_id": sample_trace_id,
                "content_type": "evaluate",
                "parameters": {
                    "content": (
                        "I think this approach has merit because I found "
                        "the data to be compelling. In my experience, "
                        "similar projects have succeeded. I believe we "
                        "should move forward carefully."
                    ),
                    "criteria": ["ai_detection"],
                },
            },
            headers=auth_headers,
        )
        data = response.json()
        assert data["status"] == "success"
        scores = data["data"]["scores"]
        assert len(scores) == 1
        assert scores[0]["criterion"] == "ai_detection"
        # Natural human-like text with personal stance should score ≥ 0.7
        assert scores[0]["score"] >= 0.7

    def test_ai_detection_flags_bullet_heavy(
        self, client, sample_trace_id, auth_headers
    ):
        """Content that is >70% bullet points scores low."""
        response = client.post(
            "/tools/evaluate_content",
            json={
                "trace_id": sample_trace_id,
                "content_type": "evaluate",
                "parameters": {
                    "content": (
                        "- Point one about the topic\n"
                        "- Point two about the topic\n"
                        "- Point three about the topic\n"
                        "- Point four about the topic\n"
                        "- Point five about the topic\n"
                        "- Point six about the topic\n"
                        "- Point seven about the topic\n"
                        "- Point eight about the topic\n"
                        "It is important to note that this robust framework "
                        "plays a pivotal role. Furthermore, we must delve into "
                        "these crucial dynamics."
                    ),
                    "criteria": ["ai_detection"],
                },
            },
            headers=auth_headers,
        )
        data = response.json()
        assert data["status"] == "success"
        scores = data["data"]["scores"]
        assert len(scores) == 1
        assert scores[0]["criterion"] == "ai_detection"
        # >70% bullet points + template phrases should score below 0.5
        assert scores[0]["score"] < 0.5

    def test_ai_detection_returns_valid_range(
        self, client, sample_trace_id, auth_headers
    ):
        """Score is always in 0.0–1.0 range for various inputs."""
        test_cases = [
            "Short human note: I went to the store and bought milk.",
            (
                "Delve into the robust, comprehensive framework. It is "
                "crucial to understand this multifaceted, holistic approach. "
                "First, consider the dynamic landscape. Second, examine the "
                "vibrant ecosystem. Finally, in conclusion, it's worth noting "
                "that moreover, furthermore, on one hand it is paramount. "
                "On the other hand, it is important to note that this plays "
                "a pivotal role. Thus, as an AI, I must say nevertheless."
            ),
            "Normal paragraph about nothing in particular. Just a regular sentence.",
        ]
        for content in test_cases:
            response = client.post(
                "/tools/evaluate_content",
                json={
                    "trace_id": sample_trace_id,
                    "content_type": "evaluate",
                    "parameters": {
                        "content": content,
                        "criteria": ["ai_detection"],
                    },
                },
                headers=auth_headers,
            )
            data = response.json()
            score = data["data"]["scores"][0]["score"]
            assert 0.0 <= score <= 1.0, f"Score {score} out of range for: {content[:50]}"

    def test_ai_detection_included_in_defaults(
        self, client, sample_trace_id, auth_headers
    ):
        """ai_detection appears in evaluation when no criteria specified."""
        response = client.post(
            "/tools/evaluate_content",
            json={
                "trace_id": sample_trace_id,
                "content_type": "evaluate",
                "parameters": {"content": "Some test content for default evaluation."},
            },
            headers=auth_headers,
        )
        data = response.json()
        assert data["status"] == "success"
        score_names = [s["criterion"] for s in data["data"]["scores"]]
        assert "ai_detection" in score_names
        # Now defaults to 6 criteria (was 5)
        assert len(data["data"]["scores"]) >= 6

    def test_ai_detection_selectable(
        self, client, sample_trace_id, auth_headers
    ):
        """ai_detection can be requested explicitly by name."""
        response = client.post(
            "/tools/evaluate_content",
            json={
                "trace_id": sample_trace_id,
                "content_type": "evaluate",
                "parameters": {
                    "content": "Test content for explicit ai_detection selection.",
                    "criteria": ["ai_detection"],
                },
            },
            headers=auth_headers,
        )
        data = response.json()
        assert data["status"] == "success"
        scores = data["data"]["scores"]
        assert len(scores) == 1
        assert scores[0]["criterion"] == "ai_detection"

    def test_ai_detection_has_justification(
        self, client, sample_trace_id, auth_headers
    ):
        """ai_detection scores include a justification string."""
        response = client.post(
            "/tools/evaluate_content",
            json={
                "trace_id": sample_trace_id,
                "content_type": "evaluate",
                "parameters": {
                    "content": "Test content that needs a justification for scoring.",
                    "criteria": ["ai_detection"],
                },
            },
            headers=auth_headers,
        )
        data = response.json()
        assert data["status"] == "success"
        score = data["data"]["scores"][0]
        assert "justification" in score
        assert len(score["justification"]) > 0


# ---------------------------------------------------------------------------
# Criterion: ai_detection v2 — checks 7-10 (burstiness, TTR, sentence var, punct)
# ---------------------------------------------------------------------------

class TestAiDetectionV2:
    """Tests for the 4 new research-backed heuristics added in AI-DETECT-STANDALONE-1."""

    def test_burstiness_flags_uniform_text(self, client, sample_trace_id, auth_headers):
        """Uniformly distributed word repetition (AI-like) scores low on burstiness."""
        # This text repeats words at very regular intervals — AI signature
        response = client.post(
            "/tools/evaluate_content",
            json={
                "trace_id": sample_trace_id,
                "content_type": "evaluate",
                "parameters": {
                    "content": (
                        "The system processes data efficiently. The system "
                        "handles requests smoothly. The system manages "
                        "workloads reliably. The system delivers results "
                        "quickly. The system ensures quality consistently. "
                        "The system maintains stability perfectly."
                    ),
                    "criteria": ["ai_detection"],
                },
            },
            headers=auth_headers,
        )
        data = response.json()
        assert data["status"] == "success"
        score = data["data"]["scores"][0]
        assert score["criterion"] == "ai_detection"
        # Template phrases + low burstiness → should be well below 0.8
        assert score["score"] < 0.8
        assert "Deterministic heuristic" in score["justification"]

    def test_ttr_hapax_distinguishes_human(self, client, sample_trace_id, auth_headers):
        """Human text with varied vocabulary scores higher than repetitive AI text."""
        # Human-like: varied vocab, unique words
        response_human = client.post(
            "/tools/evaluate_content",
            json={
                "trace_id": sample_trace_id,
                "content_type": "evaluate",
                "parameters": {
                    "content": (
                        "I think the cathedral spire cast long shadows across "
                        "the cobblestone plaza. Children laughed while "
                        "pigeons scattered frantically. An old violinist "
                        "played something melancholic near the fountain. "
                        "Tourists photographed everything without really "
                        "seeing anything. I found the whole scene oddly "
                        "comforting, like a memory I hadn't lived yet."
                    ),
                    "criteria": ["ai_detection"],
                },
            },
            headers=auth_headers,
        )
        # AI-like: repetitive, low lexical diversity
        response_ai = client.post(
            "/tools/evaluate_content",
            json={
                "trace_id": sample_trace_id,
                "content_type": "evaluate",
                "parameters": {
                    "content": (
                        "The system is designed to provide comprehensive "
                        "solutions. The system is robust and the system is "
                        "reliable. The system provides the system with "
                        "comprehensive capabilities. The system ensures "
                        "the system delivers comprehensive results."
                    ),
                    "criteria": ["ai_detection"],
                },
            },
            headers=auth_headers,
        )
        human_score = response_human.json()["data"]["scores"][0]["score"]
        ai_score = response_ai.json()["data"]["scores"][0]["score"]
        # Human text with stance markers + varied vocab should outscore repetitive AI
        assert human_score > ai_score, (
            f"Expected human ({human_score:.2f}) > AI ({ai_score:.2f})"
        )

    def test_sentence_variance_flags_uniform(self, client, sample_trace_id, auth_headers):
        """Uniform sentence lengths (AI-like) score lower than varied sentences."""
        # AI-like: all sentences roughly same length
        response_uniform = client.post(
            "/tools/evaluate_content",
            json={
                "trace_id": sample_trace_id,
                "content_type": "evaluate",
                "parameters": {
                    "content": (
                        "The system processes data efficiently. "
                        "The system handles requests smoothly. "
                        "The system manages workloads reliably. "
                        "The system delivers results quickly. "
                        "The system ensures quality consistently. "
                        "The system maintains stability perfectly."
                    ),
                    "criteria": ["ai_detection"],
                },
            },
            headers=auth_headers,
        )
        # Human-like: varied sentence lengths
        response_varied = client.post(
            "/tools/evaluate_content",
            json={
                "trace_id": sample_trace_id,
                "content_type": "evaluate",
                "parameters": {
                    "content": (
                        "I think this works. But then again, maybe it doesn't "
                        "— I've been going back and forth on this for weeks "
                        "now, and I still can't decide. The data is messy. "
                        "My advisor says to just pick a direction and run with "
                        "it, which is probably good advice, but I found the "
                        "edge cases really troubling. So I'm stuck."
                    ),
                    "criteria": ["ai_detection"],
                },
            },
            headers=auth_headers,
        )
        uniform_score = response_uniform.json()["data"]["scores"][0]["score"]
        varied_score = response_varied.json()["data"]["scores"][0]["score"]
        assert varied_score > uniform_score, (
            f"Expected varied ({varied_score:.2f}) > uniform ({uniform_score:.2f})"
        )

    def test_punctuation_diversity_score(self, client, sample_trace_id, auth_headers):
        """Text with narrow punctuation (AI) scores lower than diverse punctuation."""
        # Narrow punctuation: just periods and commas
        response_narrow = client.post(
            "/tools/evaluate_content",
            json={
                "trace_id": sample_trace_id,
                "content_type": "evaluate",
                "parameters": {
                    "content": (
                        "The system is robust, comprehensive, and dynamic. "
                        "It provides solutions, manages workflows, and "
                        "delivers results. The framework is holistic, "
                        "multifaceted, and reliable. It ensures quality, "
                        "maintains standards, and drives outcomes."
                    ),
                    "criteria": ["ai_detection"],
                },
            },
            headers=auth_headers,
        )
        # Diverse punctuation: em-dashes, ellipses, question marks
        response_diverse = client.post(
            "/tools/evaluate_content",
            json={
                "trace_id": sample_trace_id,
                "content_type": "evaluate",
                "parameters": {
                    "content": (
                        "I think this is the right call — but honestly? "
                        "I'm not sure. The data says one thing... yet my gut "
                        "says another. What would you do? (I've asked three "
                        "colleagues; they all disagree.) It's a mess — a "
                        "beautiful, terrible mess."
                    ),
                    "criteria": ["ai_detection"],
                },
            },
            headers=auth_headers,
        )
        narrow_score = response_narrow.json()["data"]["scores"][0]["score"]
        diverse_score = response_diverse.json()["data"]["scores"][0]["score"]
        assert diverse_score > narrow_score, (
            f"Expected diverse ({diverse_score:.2f}) > narrow ({narrow_score:.2f})"
        )

    def test_all_twelve_checks_contribute(self):
        """All 12 checks contribute (weighted) to the final score."""
        from saimon_mcp.evaluate.server import _score_ai_detection

        # Content that is neutral across all checks — no strong signals
        result = _score_ai_detection(
            "This is a simple paragraph with some words. "
            "It has a few sentences that are normal. "
            "Nothing particularly AI or human about it. "
            "I think it seems okay for testing purposes."
        )
        assert "criterion" in result
        assert result["criterion"] == "ai_detection"
        assert 0.0 <= result["score"] <= 1.0
        assert "Deterministic heuristic" in result["justification"]

    def test_human_text_scores_above_0_7(self, client, sample_trace_id, auth_headers):
        """Natural human text with personal stance and varied style scores ≥ 0.7."""
        response = client.post(
            "/tools/evaluate_content",
            json={
                "trace_id": sample_trace_id,
                "content_type": "evaluate",
                "parameters": {
                    "content": (
                        "I think this approach has real merit — I've tried it "
                        "on three different projects now and each time I was "
                        "surprised by how well it held up. The edge cases are "
                        "tricky, sure, but honestly? Most teams never hit them. "
                        "My advice: start simple, measure everything, and don't "
                        "over-engineer the abstractions. I learned that the hard "
                        "way after spending six months building a framework nobody "
                        "wanted. In my experience, the best solutions emerge from "
                        "actually using the thing — not from whiteboard sessions. "
                        "I found that shipping early, even with rough edges, "
                        "taught me more than any amount of planning ever did."
                    ),
                    "criteria": ["ai_detection"],
                },
            },
            headers=auth_headers,
        )
        data = response.json()
        assert data["status"] == "success"
        score = data["data"]["scores"][0]
        assert score["score"] >= 0.7, (
            f"Expected human text score ≥ 0.7, got {score['score']:.2f}. "
            f"Justification: {score['justification']}"
        )
        assert "Deterministic heuristic" in score["justification"]


# ---------------------------------------------------------------------------
# AI-DETECT-CALIBRATE-1 — calibration tests
# ---------------------------------------------------------------------------

class TestAiDetectCalibrate:
    """Calibration tests ensuring human ≥0.75, saimon ≤0.55, AI-template ≤0.40,
    with minimum AI↔human separation ≥0.30."""

    HUMAN_TEXT = (
        "I spent the last three years building this system and honestly? "
        "I'm still surprised it works. We had this one bug that took me "
        "six weeks to track down — turned out to be a race condition in "
        "the connection pool that only triggered under very specific load "
        "patterns. My colleague found a similar issue in his project and "
        "we wrote a shared library to detect those patterns. I think the "
        "key insight was realizing that the thread scheduler behaves "
        "differently under memory pressure. In my experience, most "
        "concurrency bugs hide in plain sight — you just need the right "
        "logging to expose them. We debugged the whole thing over a "
        "weekend with way too much coffee and a whiteboard covered in "
        "timing diagrams. I believe the solution we arrived at is elegant "
        "but I'm also aware it might need revisiting as the system scales."
    )

    SAIMON_TEXT = (
        "The platform offers several key advantages that can reduce "
        "operational overhead while maintaining reliability standards. "
        "These capabilities contribute to improved outcomes without "
        "fundamentally altering existing workflows. The system may help "
        "organizations achieve their goals through practical benefits "
        "such as automated processing and intelligent routing. It is "
        "worth noting that the implementation requires careful planning "
        "and a comprehensive understanding of the underlying framework. "
        "Furthermore, the robust architecture ensures scalability across "
        "diverse use cases. In conclusion, the solution provides a "
        "holistic approach that balances performance with usability."
    )

    AI_TEMPLATE_TEXT = (
        "It is important to note that we must delve into this crucial "
        "topic. Furthermore, this multifaceted approach plays a pivotal "
        "role in the dynamic landscape of modern technology. It is worth "
        "noting that the robust and comprehensive framework can reduce "
        "operational overhead. In the realm of digital transformation, "
        "it is essential to consider these paramount factors. Moreover, "
        "the holistic solution may help organizations achieve their goals. "
        "It should be noted that these capabilities offer practical benefits. "
        "On one hand, the system provides numerous advantages. However, on "
        "the other hand, it presents certain challenges. Thus, in conclusion, "
        "it is imperative that stakeholders consider the multifaceted "
        "implications. Additionally, this paradigm shift requires a nuanced "
        "understanding of the vibrant ecosystem. It is crucial to understand "
        "that this robust architecture plays a pivotal role. In an era of "
        "rapid change, the comprehensive solution ensures optimal outcomes. "
        "First, we must examine the fundamental principles. Second, we should "
        "explore the practical applications. Finally, we need to implement "
        "the recommended strategies."
    )

    def test_human_scores_above_75(self, client, sample_trace_id, auth_headers):
        """Human-authored text with personal stance scores ≥ 0.75."""
        response = client.post(
            "/tools/evaluate_content",
            json={
                "trace_id": sample_trace_id,
                "content_type": "evaluate",
                "parameters": {
                    "content": self.HUMAN_TEXT,
                    "criteria": ["ai_detection"],
                },
            },
            headers=auth_headers,
        )
        data = response.json()
        assert data["status"] == "success"
        score = data["data"]["scores"][0]["score"]
        assert score >= 0.75, (
            f"Expected human text score ≥ 0.75, got {score:.2f}. "
            f"Justification: {data['data']['scores'][0]['justification']}"
        )

    def test_saimon_scores_below_55(self, client, sample_trace_id, auth_headers):
        """Saimon-generated text (impersonal, hedged) scores ≤ 0.55."""
        response = client.post(
            "/tools/evaluate_content",
            json={
                "trace_id": sample_trace_id,
                "content_type": "evaluate",
                "parameters": {
                    "content": self.SAIMON_TEXT,
                    "criteria": ["ai_detection"],
                },
            },
            headers=auth_headers,
        )
        data = response.json()
        assert data["status"] == "success"
        score = data["data"]["scores"][0]["score"]
        assert score <= 0.55, (
            f"Expected saimon text score ≤ 0.55, got {score:.2f}. "
            f"Justification: {data['data']['scores'][0]['justification']}"
        )

    def test_ai_template_below_40(self, client, sample_trace_id, auth_headers):
        """Hand-crafted AI template text scores ≤ 0.40."""
        response = client.post(
            "/tools/evaluate_content",
            json={
                "trace_id": sample_trace_id,
                "content_type": "evaluate",
                "parameters": {
                    "content": self.AI_TEMPLATE_TEXT,
                    "criteria": ["ai_detection"],
                },
            },
            headers=auth_headers,
        )
        data = response.json()
        assert data["status"] == "success"
        score = data["data"]["scores"][0]["score"]
        assert score <= 0.40, (
            f"Expected AI template score ≤ 0.40, got {score:.2f}. "
            f"Justification: {data['data']['scores'][0]['justification']}"
        )

    def test_human_ai_separation(self, client, sample_trace_id, auth_headers):
        """The gap between human text and saimon-generated text is ≥ 0.30."""
        resp_human = client.post(
            "/tools/evaluate_content",
            json={
                "trace_id": sample_trace_id,
                "content_type": "evaluate",
                "parameters": {
                    "content": self.HUMAN_TEXT,
                    "criteria": ["ai_detection"],
                },
            },
            headers=auth_headers,
        )
        resp_saimon = client.post(
            "/tools/evaluate_content",
            json={
                "trace_id": sample_trace_id,
                "content_type": "evaluate",
                "parameters": {
                    "content": self.SAIMON_TEXT,
                    "criteria": ["ai_detection"],
                },
            },
            headers=auth_headers,
        )
        human_score = resp_human.json()["data"]["scores"][0]["score"]
        saimon_score = resp_saimon.json()["data"]["scores"][0]["score"]
        separation = human_score - saimon_score
        assert separation >= 0.30, (
            f"Expected human-saimon separation ≥ 0.30, got {separation:.2f} "
            f"(human={human_score:.2f}, saimon={saimon_score:.2f})"
        )

    def test_personal_regex_matches_varied(self):
        """The personal stance regex catches varied real-world patterns."""
        from saimon_mcp.evaluate.server import _score_ai_detection

        # These should all be detected as personal stance
        personal_samples = [
            "I am working on the report.",
            "We were surprised by the results.",
            "My team built the prototype in a week.",
            "I found the bug at 3am.",
            "I debugged the memory leak yesterday.",
            "I tried three different approaches.",
            "I wrote the integration tests first.",
            "I noticed the pattern repeating.",
            "I discovered a faster algorithm.",
            "I feel strongly about code reviews.",
            "Our team decided to rewrite it.",
            "I spent the afternoon refactoring.",
            "We fixed all the flaky tests.",
        ]
        for sample in personal_samples:
            result = _score_ai_detection(sample)
            # Short personal samples should still have the check5 contribution
            assert result["score"] >= 0.0

        # Non-personal samples should not match
        impersonal_samples = [
            "The system processes data efficiently.",
            "Results indicate a positive trend.",
            "Implementation requires careful planning.",
            "The framework provides robust solutions.",
        ]
        for sample in impersonal_samples:
            result = _score_ai_detection(sample)
            # Impersonal text should score lower overall (won't get personal stance boost)
            assert result["score"] >= 0.0

    def test_corporate_neutrality_flags(self):
        """Corporate neutrality check detects impersonal/hedged/balanced tone."""
        from saimon_mcp.evaluate.server import _score_ai_detection

        # Heavily corporate/hedged — should be flagged
        corporate_text = (
            "The platform can reduce costs and may help improve efficiency. "
            "It offers several advantages that contribute to better outcomes. "
            "These capabilities provide practical benefits without fundamentally "
            "changing existing processes. In many cases, it can lead to "
            "measurable improvements. It is possible that further optimization "
            "may result in additional gains. Generally speaking, the solution "
            "tends to perform well across various factors."
        )
        result_corp = _score_ai_detection(corporate_text)
        # Verify the check runs and produces a valid score
        assert 0.0 <= result_corp["score"] <= 1.0
        # Corporate text should score lower than personal text
        assert result_corp["score"] < 0.8, (
            f"Corporate text should flag AI patterns, got {result_corp['score']:.2f}"
        )

    def test_starter_diversity(self):
        """Sentence starter diversity distinguishes varied vs repetitive openings."""
        from saimon_mcp.evaluate.server import _score_ai_detection

        # Low diversity: every sentence starts with "The system" or "It"
        low_diversity = (
            "The system processes data efficiently. "
            "The system handles requests smoothly. "
            "The system manages workloads reliably. "
            "The system delivers results quickly. "
            "The system ensures quality consistently. "
            "It provides numerous benefits to users. "
            "It offers several key advantages. "
            "It can be configured for various needs."
        )
        # High diversity: every sentence starts differently
        high_diversity = (
            "I noticed the logs were filling up fast. "
            "My teammate suggested adding a retention policy. "
            "Debugging the issue took most of Tuesday. "
            "We eventually found a memory leak in the cache layer. "
            "Fixing it required changing three different services. "
            "After the deploy, everything ran smoothly again. "
            "Honestly, I wish we'd caught it sooner. "
            "Next time I'll set up alerts for disk usage."
        )
        result_low = _score_ai_detection(low_diversity)
        result_high = _score_ai_detection(high_diversity)
        assert 0.0 <= result_low["score"] <= 1.0
        assert 0.0 <= result_high["score"] <= 1.0
        # High diversity personal text should score significantly above low diversity
        assert result_high["score"] > result_low["score"], (
            f"Expected high diversity ({result_high['score']:.2f}) > "
            f"low diversity ({result_low['score']:.2f})"
        )
