"""Four-arm release A/B: baseline agent, agent + RAG, previous release, current release.

The arms differ in exactly one thing - what context the generator sees - so a difference
between two arms is attributable to retrieval and nothing else:

    baseline   model alone, no context
    rag        top-K passages from the RAG endpoint, gated abstention IGNORED
    previous   top-K passages from the previous release's endpoint, abstention respected
    current    top-K passages from the current release's endpoint, abstention respected

Generation is held constant across all four arms. That is deliberate: swapping the model
between arms confounds the comparison, which is the failure the harness research names
(harness and model effects cannot be separated after the fact).

Every task is graded on facts the answer must contain, or on refusing to answer when the
corpus does not cover the topic. A release that answers more questions by fabricating
fails the abstention metric even when its success rate rises.
"""

from __future__ import annotations

import json
import math
import random
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

SCHEMA_VERSION = 1

REFUSAL_PATTERNS = (
    "i don't know",
    "i do not know",
    "not in the context",
    "does not contain",
    "no information",
    "cannot answer",
    "can't answer",
    "unable to answer",
    "no strong evidence",
)

WORLD_KNOWLEDGE_PROMPT = (
    "Answer the question in three sentences or fewer. If you are not sure, say you do not know.\n\n"
    "Question: {query}\nAnswer:"
)

DEFAULT_PROMPT = (
    "Answer the question using only the context below. Keep it to three sentences.\n"
    "If the context does not contain the answer, say you do not know.\n\n"
    "Context:\n{context}\n\nQuestion: {query}\nAnswer:"
)

NO_CONTEXT = "(no context provided)"


@dataclass(frozen=True)
class Arm:
    id: str
    label: str
    retrieval: str | None  # endpoint key: "rag", "previous", "current", or None
    respect_gate: bool = True
    world_knowledge: bool = False


ARMS: tuple[Arm, ...] = (
    Arm("baseline", "Baseline agent (no retrieval)", None, world_knowledge=True),
    Arm("rag", "Agent + RAG (gated abstention ignored)", "rag", respect_gate=False),
    Arm("previous", "Previous Saimon release", "previous"),
    Arm("current", "Current Saimon release", "current"),
)


@dataclass
class ArmConfig:
    urls: dict[str, str] = field(default_factory=dict)
    limit: int = 5
    model: str = "deepseek-v4-flash"
    prompt: str = DEFAULT_PROMPT
    # USD per 1M tokens; estimates only, labelled as such in the report.
    input_usd_per_mtok: float = 0.27
    output_usd_per_mtok: float = 1.10


def load_tasks(path: str) -> list[dict[str, Any]]:
    with open(path, encoding="utf-8") as handle:
        data = json.load(handle)
    tasks = data.get("tasks", data if isinstance(data, list) else [])
    for task in tasks:
        for key in ("id", "kind", "query"):
            if key not in task:
                raise ValueError(f"task missing {key!r}: {task!r}")
        if task["kind"] not in {"answerable", "unanswerable"}:
            raise ValueError(f"task {task['id']} has unknown kind {task['kind']!r}")
    return tasks


def is_refusal(text: str) -> bool:
    lowered = (text or "").lower()
    return any(pattern in lowered for pattern in REFUSAL_PATTERNS)


def score_answer(text: str, task: dict[str, Any]) -> dict[str, Any]:
    """Grade one answer against its task.

    Answerable: success only when every required fact appears and the agent did not refuse.
    Unanswerable: success only when the agent refused. A confident wrong answer is a failure
    even though it looks like a better user experience.
    """
    body = (text or "").lower()
    refused = is_refusal(text)
    missing = [fact for fact in task.get("must_include", []) if fact.lower() not in body]

    if task["kind"] == "unanswerable":
        return {"success": refused, "abstained": refused, "missing": [], "kind": task["kind"]}
    return {
        "success": (not refused) and not missing,
        "abstained": refused,
        "missing": missing,
        "kind": task["kind"],
    }


def groundedness(context: str, task: dict[str, Any]) -> float | None:
    """Fraction of the required facts present in the retrieved context.

    Answers this question: did the retrieval hand the generator the fact it needed, or did
    the model supply it from training data? A rising success rate with flat groundedness is
    a model change, not a retrieval improvement.
    """
    facts = task.get("must_include", [])
    if not facts:
        return None
    body = (context or "").lower()
    return round(sum(1 for fact in facts if fact.lower() in body) / len(facts), 4)


def build_prompt(query: str, context: str, template: str = DEFAULT_PROMPT) -> str:
    return template.replace("{context}", context or NO_CONTEXT).replace("{query}", query)


def estimate_tokens(text: str) -> int:
    """Rough token count: four characters per token, floored at one word."""
    stripped = (text or "").strip()
    if not stripped:
        return 0
    return max(len(stripped) // 4, len(stripped.split()))


def estimate_cost_usd(prompt: str, answer: str, cfg: ArmConfig) -> float:
    cost = (
        estimate_tokens(prompt) * cfg.input_usd_per_mtok
        + estimate_tokens(answer) * cfg.output_usd_per_mtok
    ) / 1_000_000
    return round(cost, 8)


def percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = max(0, math.ceil(pct / 100 * len(ordered)) - 1)
    return ordered[index]


def run_arm(
    arm: Arm,
    tasks: list[dict[str, Any]],
    cfg: ArmConfig,
    *,
    generate: Callable[[str], str],
    search: Callable[[str, str, int], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Run every task through one arm. *search* is optional for the baseline arm."""
    rows: list[dict[str, Any]] = []
    for task in tasks:
        context = ""
        retrieval_ms = 0.0
        gate_fired = False
        retrieved = 0

        if arm.retrieval is not None:
            url = cfg.urls.get(arm.retrieval, "")
            if not url:
                return {
                    "id": arm.id,
                    "label": arm.label,
                    "skipped": f"no URL configured for {arm.retrieval!r}",
                    "rows": [],
                    "summary": {},
                }
            started = time.perf_counter()
            payload = search(url, task["query"], cfg.limit) if search else {}
            retrieval_ms = (time.perf_counter() - started) * 1000
            gate_fired = bool(payload.get("no_strong_evidence"))
            results = [] if (gate_fired and arm.respect_gate) else payload.get("results", [])
            retrieved = len(results)
            context = "\n\n".join(
                f"[{row.get('id', '')[:8]}] {row.get('title', '')}: {row.get('body', '')}".strip()
                for row in results
            )

        template = WORLD_KNOWLEDGE_PROMPT if arm.world_knowledge else cfg.prompt
        prompt = build_prompt(task["query"], context, template)
        started = time.perf_counter()
        answer = generate(prompt)
        generate_ms = (time.perf_counter() - started) * 1000

        graded = score_answer(answer, task)
        rows.append(
            {
                "task_id": task["id"],
                "kind": task["kind"],
                "answer": answer,
                "success": graded["success"],
                "abstained": graded["abstained"],
                "missing": graded["missing"],
                "retrieved": retrieved,
                "gate_fired": gate_fired,
                "groundedness": groundedness(context, task),
                "retrieval_ms": round(retrieval_ms, 2),
                "generate_ms": round(generate_ms, 2),
                "latency_ms": round(retrieval_ms + generate_ms, 2),
                "cost_usd": estimate_cost_usd(prompt, answer, cfg),
            }
        )

    return {
        "id": arm.id,
        "label": arm.label,
        "skipped": None,
        "rows": rows,
        "summary": summarise(rows),
    }


def summarise(rows: list[dict[str, Any]]) -> dict[str, Any]:
    if not rows:
        return {}
    answerable = [r for r in rows if r["kind"] == "answerable"]
    unanswerable = [r for r in rows if r["kind"] == "unanswerable"]
    grounded = [r["groundedness"] for r in rows if r["groundedness"] is not None]
    latencies = [r["latency_ms"] for r in rows]

    return {
        "tasks": len(rows),
        "success_rate": round(sum(1 for r in rows if r["success"]) / len(rows), 4),
        "answerable_success_rate": (
            round(sum(1 for r in answerable if r["success"]) / len(answerable), 4)
            if answerable
            else None
        ),
        "abstain_accuracy": (
            round(sum(1 for r in unanswerable if r["success"]) / len(unanswerable), 4)
            if unanswerable
            else None
        ),
        "groundedness_mean": round(sum(grounded) / len(grounded), 4) if grounded else None,
        "latency_p50_ms": round(percentile(latencies, 50), 2),
        "latency_p95_ms": round(percentile(latencies, 95), 2),
        "cost_total_usd": round(sum(r["cost_usd"] for r in rows), 8),
        "cost_mean_usd": round(sum(r["cost_usd"] for r in rows) / len(rows), 8),
    }


def paired_bootstrap(
    arm_a: list[dict[str, Any]],
    arm_b: list[dict[str, Any]],
    *,
    samples: int = 2000,
    seed: int = 7,
) -> dict[str, Any]:
    """Mean paired difference (b - a) on task success, with a 95% CI.

    Paired by task id, so a release that fixes one task and breaks another does not look
    like a wash: the per-task differences are resampled, not the two means.
    """
    by_id_a = {r["task_id"]: 1.0 if r["success"] else 0.0 for r in arm_a}
    by_id_b = {r["task_id"]: 1.0 if r["success"] else 0.0 for r in arm_b}
    shared = sorted(set(by_id_a) & set(by_id_b))
    if not shared:
        return {"tasks": 0, "mean_diff": None, "ci95": None}

    diffs = [by_id_b[t] - by_id_a[t] for t in shared]
    rng = random.Random(seed)
    means = []
    for _ in range(samples):
        draw = [diffs[rng.randrange(len(diffs))] for _ in diffs]
        means.append(sum(draw) / len(draw))
    means.sort()
    return {
        "tasks": len(shared),
        "mean_diff": round(sum(diffs) / len(diffs), 4),
        "ci95": [round(means[int(0.025 * samples)], 4), round(means[int(0.975 * samples) - 1], 4)],
        "improved": sum(1 for d in diffs if d > 0),
        "regressed": sum(1 for d in diffs if d < 0),
    }


def evaluate_gate(report: dict[str, Any], targets: dict[str, Any]) -> dict[str, Any]:
    """Check a report against pre-registered release goals.

    A missing arm yields a *skipped* check with its reason, never a pass: an unmeasured
    goal is not a met goal.
    """
    arms = {arm["id"]: arm for arm in report.get("arms", [])}
    thresholds = targets.get("thresholds", {})
    checks: list[dict[str, Any]] = []

    def summary(arm_id: str) -> dict[str, Any] | None:
        arm = arms.get(arm_id)
        if not arm or arm.get("skipped"):
            return None
        return arm.get("summary") or {}

    current = summary("current")
    baseline = summary("baseline")
    previous = summary("previous")

    def check(name: str, ok: bool | None, detail: str) -> None:
        checks.append({"check": name, "status": "fail" if ok is False else ("pass" if ok else "skipped"), "detail": detail})

    if current and baseline:
        gap = (current.get("success_rate") or 0) - (baseline.get("success_rate") or 0)
        need = thresholds.get("current_vs_baseline_success_gain", 0.15)
        check("current_vs_baseline_success_gain", gap >= need, f"{gap:+.3f} vs minimum +{need:.3f}")
    else:
        check("current_vs_baseline_success_gain", None, "baseline or current arm missing")

    if current and previous:
        drop = (previous.get("success_rate") or 0) - (current.get("success_rate") or 0)
        allowed = thresholds.get("current_vs_previous_success_drop_max", 0.02)
        check("current_vs_previous_success_drop", drop <= allowed, f"drop {drop:+.3f} vs allowed {allowed:.3f}")
    else:
        check("current_vs_previous_success_drop", None, "previous release arm not measured")

    if current:
        need = thresholds.get("current_abstain_accuracy_min", 1.0)
        got = current.get("abstain_accuracy")
        check("current_abstain_accuracy", got is not None and got >= need, f"{got} vs minimum {need}")

        need = thresholds.get("current_groundedness_min", 0.75)
        got = current.get("groundedness_mean")
        check("current_groundedness", got is not None and got >= need, f"{got} vs minimum {need}")

    if current and previous and previous.get("latency_p95_ms"):
        ratio = (current.get("latency_p95_ms") or 0) / previous["latency_p95_ms"]
        allowed = thresholds.get("current_p95_latency_ratio_max", 1.5)
        check("current_p95_latency_ratio", ratio <= allowed, f"x{ratio:.2f} vs maximum x{allowed:.2f}")

    if current and previous and previous.get("cost_mean_usd"):
        ratio = (current.get("cost_mean_usd") or 0) / previous["cost_mean_usd"]
        allowed = thresholds.get("current_cost_ratio_vs_previous_max", 1.2)
        check("current_cost_ratio", ratio <= allowed, f"x{ratio:.2f} vs maximum x{allowed:.2f}")
    else:
        check("current_cost_ratio", None, "previous release arm not measured")

    failed = [c for c in checks if c["status"] == "fail"]
    return {
        "verdict": "FAIL" if failed else ("PASS" if any(c["status"] == "pass" for c in checks) else "UNMEASURED"),
        "checks": checks,
    }
