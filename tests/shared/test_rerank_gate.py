

def test_duplicate_records_are_not_ambiguity():
    """Two rows naming one entity are one answer (#266).

    Live case: two "Sergeant Kade" nodes at 0.79/0.78 made the margin gate abstain
    on a question the corpus answers. Duplicate rows need tidying, not abstaining.
    """
    from research_shared.rerank import RerankConfig, gate_decision

    scored = [
        {"relevance_score": 0.79, "title": "Sergeant Kade", "unit_id": None},
        {"relevance_score": 0.78, "title": "sergeant   kade", "unit_id": None},
    ]
    abstain, _top, _gap = gate_decision(scored, RerankConfig())
    assert abstain is False


def test_different_entities_still_abstain_on_a_close_gap():
    from research_shared.rerank import RerankConfig, gate_decision

    scored = [
        {"relevance_score": 0.79, "title": "Sergeant Kade", "unit_id": None},
        {"relevance_score": 0.78, "title": "Sergeant Doyle", "unit_id": None},
    ]
    abstain, _top, _gap = gate_decision(scored, RerankConfig())
    assert abstain is True
