#!/usr/bin/env python3
"""Golden quality corpus runner (SAIMON-GOLDEN-EVAL-BASELINE-1).

Two modes:

  live    measure the running stack against fixtures/golden/suite.json and write
          a report (retrieval, degraded, claim structure; verification opt-in).
  verify  re-score a committed report with the rubrics and compare it to a
          baseline. Pure offline — this is the mode CI runs.

A report is the unit of evidence: it records the measured dimensions, the raw
per-case observations that produced them, and the environment it ran against.
Nothing is inferred from a log line.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
import uuid
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from eval_harness.rubrics import (
    VERDICT_INCOMPLETE,
    compare_to_baseline,
    load_rubrics,
    score_report,
)

ROOT = Path(__file__).resolve().parents[1]
SUITE = ROOT / "fixtures" / "golden" / "suite.json"

NUMBER_RE = re.compile(r"\d")
UNIT_RE = re.compile(
    r"\b(%|percent|minute|minutes|hour|hours|day|days|week|weeks|month|months|"
    r"year|years|request|requests|dollar|dollars|kg|km|ms|seconds?)\b",
    re.IGNORECASE,
)
VERB_RE = re.compile(
    r"\b(is|are|was|were|be|been|has|have|had|do|does|did|report|reports|show|shows|"
    r"take|takes|took|degrade|degrades|drop|drops|handle|handled|require|requires|"
    r"increase|increases|decrease|decreases|use|uses|produce|produces)\b",
    re.IGNORECASE,
)
LEADER_RE = re.compile(r"\.{4,}")


def _api_key(name: str) -> str | None:
    if os.getenv(name):
        return os.environ[name]
    cfg = Path("/home/hermes/.hermes/profiles/director/config.yaml")
    if cfg.is_file():
        try:
            import yaml

            data = yaml.safe_load(cfg.read_text())
            return (
                ((data.get("mcp_servers") or {}).get("saimon-researcher") or {})
                .get("env", {})
                .get(name)
            )
        except Exception:  # noqa: BLE001 — key lookup is best-effort
            return None
    return None


def _post(url: str, key: str, tool: str, params: dict, timeout: int = 60) -> tuple[int, dict]:
    body = json.dumps(
        {"trace_id": str(uuid.uuid4()), "content_type": "probe", "parameters": params}
    ).encode()
    req = urllib.request.Request(
        f"{url}/tools/{tool}",
        data=body,
        headers={"Content-Type": "application/json", "X-Saimon-API-Key": key},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        return exc.code, {"status": "error", "errors": [f"HTTP {exc.code}"]}


# ---------------------------------------------------------------------------
# offline measurements
# ---------------------------------------------------------------------------


def looks_like_claim(text: str) -> bool:
    """Structural claim test — no model, no network."""
    stripped = " ".join((text or "").split())
    if len(stripped.split()) < 4:
        return False
    if LEADER_RE.search(stripped):
        return False
    if VERB_RE.search(stripped) and NUMBER_RE.search(stripped):
        return True
    return bool(VERB_RE.search(stripped))


def is_name_list(text: str) -> bool:
    stripped = " ".join((text or "").split())
    if NUMBER_RE.search(stripped) or "," not in stripped:
        return False
    segments = [s.strip() for s in stripped.split(",") if s.strip()]
    if len(segments) < 2:
        return False
    name_like = 0
    for segment in segments:
        words = segment.split()
        if not words or len(words) > 4:
            continue
        if all(w[:1].isupper() and w.replace(".", "").isalpha() for w in words):
            name_like += 1
    return name_like / len(segments) >= 0.6


def measure_claims(cases: list[dict]) -> tuple[dict, list[dict]]:
    rows: list[dict] = []
    all_match = 0
    numeric_ok = 0
    numeric_total = 0
    noise_ok = 0
    noise_total = 0
    for case in cases:
        text = case["claim_text"]
        expect = case["expect"]
        observed = {
            "has_number": bool(NUMBER_RE.search(text)),
            "has_unit": bool(UNIT_RE.search(text)),
            "has_verb": bool(VERB_RE.search(text)),
            "is_name_list": is_name_list(text),
        }
        matches = {key: observed[key] == expect[key] for key in expect}
        all_match += int(all(matches.values()))
        if expect.get("has_number"):
            numeric_total += 1
            numeric_ok += int(observed["has_number"])
        expected_noise = expect.get("is_name_list") or not looks_like_claim(text)
        if expected_noise:
            noise_total += 1
            noise_ok += int(not looks_like_claim(text))
        rows.append({"id": case["id"], "observed": observed, "expected": expect,
                     "matched": matches, "looks_like_claim": looks_like_claim(text)})
    total = len(cases) or 1
    dimensions = {
        "structural_precision": all_match / total,
        "numeric_signal": (numeric_ok / numeric_total) if numeric_total else None,
        "noise_rejection": (noise_ok / noise_total) if noise_total else None,
    }
    return dimensions, rows


# ---------------------------------------------------------------------------
# live measurements
# ---------------------------------------------------------------------------


def measure_retrieval(cases: list[dict], url: str, key: str, limit: int = 3) -> tuple[dict, list[dict]]:
    rows: list[dict] = []
    hits = 0
    floors = 0
    floor_total = 0
    provenance_ok = 0
    provenance_total = 0
    abstain_ok = 0
    abstain_total = 0
    for case in cases:
        status, payload = _post(url, key, "search_knowledge_graph",
                                {"query": case["query"], "limit": limit})
        results = ((payload.get("data") or {}).get("results") or [])
        titles = [str(r.get("title") or "") for r in results]
        scores = [r.get("relevance_score") for r in results]
        if case.get("expect_empty"):
            abstain_total += 1
            ok = status == 200 and len(results) == 0
            abstain_ok += int(ok)
            rows.append({"id": case["id"], "kind": "abstain", "ok": ok, "hits": len(results)})
            continue
        hit = any(case["expect_title"].lower() in t.lower() for t in titles)
        hits += int(hit)
        floor_total += 1
        top = scores[0] if scores else None
        floors += int(top is not None and float(top) >= float(case["floor"]))
        provenance_total += len(results)
        provenance_ok += sum(1 for s in scores if s is not None)
        rows.append({"id": case["id"], "kind": "retrieval", "hit": hit,
                     "top_score": top, "titles": titles[:3], "status": status})
    dimensions = {
        "hit_rate": hits / max(1, floor_total),
        "score_floor": (floors / floor_total) if floor_total else None,
        "abstention": (abstain_ok / abstain_total) if abstain_total else None,
        "provenance": (provenance_ok / provenance_total) if provenance_total else None,
    }
    return dimensions, rows


def measure_degraded(cases: list[dict], url: str, key: str) -> tuple[dict, list[dict]]:
    rows: list[dict] = []
    distinguished = 0
    reasons = 0
    for case in cases:
        if case["tool"] == "search":
            _, payload = _post(url, key, "search_knowledge_graph",
                               {"query": case["query"], "limit": 3})
            results = ((payload.get("data") or {}).get("results") or [])
            refused = payload.get("status") == "error" or bool(payload.get("errors"))
            empty = payload.get("status") != "error" and len(results) == 0
            if case["expect"] == "refused":
                ok = refused
            else:
                ok = empty and not refused
            distinguished += int(ok)
            reasons += int(bool(payload.get("errors")))
            rows.append({"id": case["id"], "ok": ok, "refused": refused, "results": len(results)})
        else:
            _, payload = _post(url, key, "ingest_document",
                                    {"url": case["url"], "title": "probe"}, timeout=30)
            refused = payload.get("status") == "error" or bool(payload.get("errors"))
            distinguished += int(refused)
            reasons += int(bool(payload.get("errors")))
            rows.append({"id": case["id"], "ok": refused, "refused": refused})
    total = len(cases) or 1
    return (
        {"fail_closed_distinction": distinguished / total,
         "degradation_reason_presence": reasons / total},
        rows,
    )


def measure_verification(cases: list[dict], url: str, key: str) -> tuple[dict, list[dict]]:
    rows: list[dict] = []
    bound = 0
    complete = 0
    sane = 0
    for case in cases:
        t0 = time.time()
        _, payload = _post(url, key, "verify_claim",
                                {"claim": case["claim_text"]}, timeout=180)
        data = payload.get("data") or {}
        evidence = data.get("verifications") or data.get("evidence") or []
        has_source = any(
            isinstance(item, dict) and item.get("evidence_source") for item in evidence
        )
        bound += int(has_source)
        ledger_ok = bool(data.get("overall_verdict")) and data.get("overall_confidence") is not None \
            and len(evidence) > 0
        complete += int(ledger_ok)
        verdict = str(data.get("overall_verdict") or "").lower()
        sane += int(verdict in [s.lower() for s in case["expect_status_any"]])
        rows.append({"id": case["id"], "verdict": verdict, "evidence_items": len(evidence),
                     "has_evidence_source": has_source, "ledger_ok": ledger_ok,
                     "ms": int((time.time() - t0) * 1000)})
    total = len(cases) or 1
    return (
        {"evidence_binding": bound / total,
         "ledger_completeness": complete / total,
         "status_sanity": sane / total},
        rows,
    )


# ---------------------------------------------------------------------------
# commands
# ---------------------------------------------------------------------------


def cmd_live(args: argparse.Namespace) -> int:
    suite = json.loads(SUITE.read_text())
    rubrics = load_rubrics(SUITE)
    search_key = _api_key("SAIMON_SEARCH_KEY")
    if not search_key:
        print("SAIMON_SEARCH_KEY is not set", file=sys.stderr)
        return 2
    dimensions: dict[str, dict] = {}
    observations: dict[str, list] = {}

    dimensions["retrieval-rubric-v1"], observations["retrieval"] = measure_retrieval(
        suite["cases"]["retrieval"], args.search_url, search_key
    )
    dimensions["claim-rubric-v1"], observations["claim"] = measure_claims(suite["cases"]["claim"])
    dimensions["degraded-rubric-v1"], observations["degraded"] = measure_degraded(
        suite["cases"]["degraded"], args.search_url, search_key
    )
    if args.with_verify:
        verify_key = _api_key("SAIMON_VERIFY_KEY") or search_key
        dimensions["verification-rubric-v1"], observations["verification"] = measure_verification(
            suite["cases"]["verification"], args.verify_url, verify_key
        )

    report = {
        "schema_version": 1,
        "generated_at": datetime.now(UTC).isoformat(),
        "mode": "live",
        "environment": {
            "search_url": args.search_url,
            "verify_url": args.verify_url if args.with_verify else None,
            "git_revision": _git_revision(),
        },
        "dimensions": dimensions,
        "observations": observations,
    }
    report["scored"] = score_report(report, rubrics)
    out = Path(args.out) if args.out else ROOT / "reports" / f"golden-{_stamp()}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n")
    print(json.dumps(report["scored"], indent=2))
    print(f"report written to {out}")
    return 0 if report["scored"]["overall_verdict"] != VERDICT_INCOMPLETE else 1


def cmd_verify(args: argparse.Namespace) -> int:
    rubrics = load_rubrics(SUITE)
    report = json.loads(Path(args.report).read_text())
    rescored = score_report(report, rubrics)
    problems: list[str] = []
    if report.get("scored") and report["scored"].get("overall_verdict") != rescored["overall_verdict"]:
        problems.append(
            f"recorded verdict {report['scored'].get('overall_verdict')} != recomputed {rescored['overall_verdict']}"
        )
    result = {"rescored": rescored, "problems": problems}
    if args.baseline:
        baseline = json.loads(Path(args.baseline).read_text())
        comparison = compare_to_baseline(baseline, report, tolerance=args.tolerance)
        result["comparison"] = comparison
        if comparison["verdict"] != "OK":
            problems.extend(
                f"{r['rubric']}.{r['dimension']}: {r['reason']}" for r in comparison["regressions"]
            )
    result["verdict"] = "OK" if not problems else "REGRESSION"
    print(json.dumps(result, indent=2))
    return 0 if not problems else 1


def _git_revision() -> str | None:
    try:
        import subprocess

        return subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, text=True
        ).strip()
    except Exception:  # noqa: BLE001
        return None


def _stamp() -> str:
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Golden quality corpus runner")
    sub = parser.add_subparsers(dest="command", required=True)

    live = sub.add_parser("live", help="measure the running stack and write a report")
    live.add_argument("--search-url", default=os.getenv("SAIMON_SEARCH_URL", "http://127.0.0.1:8101"))
    live.add_argument("--verify-url", default=os.getenv("SAIMON_VERIFY_URL", "http://127.0.0.1:8105"))
    live.add_argument("--with-verify", action="store_true", help="also measure verify_claim (slow)")
    live.add_argument("--out", help="report path (default reports/golden-<stamp>.json)")
    live.set_defaults(func=cmd_live)

    verify = sub.add_parser("verify", help="re-score a report offline and compare to a baseline")
    verify.add_argument("--report", required=True)
    verify.add_argument("--baseline")
    verify.add_argument("--tolerance", type=float, default=0.05)
    verify.set_defaults(func=cmd_verify)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
