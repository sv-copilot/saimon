"""Claim identity: the hash must be stable across whitespace/case, and distinct
for distinct claims — it is the only thing preventing duplicate claim nodes on
re-runs of the extraction batch.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

_PATH = Path(__file__).resolve().parents[2] / "scripts" / "extract_claims_batch.py"
_spec = importlib.util.spec_from_file_location("extract_claims_batch", _PATH)
_mod = importlib.util.module_from_spec(_spec)
assert _spec and _spec.loader
_spec.loader.exec_module(_mod)


class TestClaimHash:
    def test_normalise_collapses_whitespace_and_case(self):
        assert _mod.normalise("  The   Model\tWorks\n") == "the model works"

    def test_same_claim_different_formatting_hashes_equal(self):
        a = _mod.claim_hash("Accuracy degrades 30%.")
        b = _mod.claim_hash("  accuracy   degrades 30%. ")
        assert a == b

    def test_distinct_claims_hash_differently(self):
        assert _mod.claim_hash("Accuracy degrades 30%.") != _mod.claim_hash("Accuracy degrades 31%.")

    def test_hash_is_short_and_hex(self):
        h = _mod.claim_hash("a claim")
        assert len(h) == 24
        assert all(c in "0123456789abcdef" for c in h)
