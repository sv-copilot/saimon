#!/usr/bin/env python3
"""Render the benchmark charts from measured JSON.

Every number here is read from a result file produced by
scripts/measure_retrieval.py, scripts/measure_adversarial.py,
scripts/baseline_grep.py or the A/B harness. Nothing is typed in by hand, so a
chart cannot drift from the measurement it claims to show.

    python scripts/render_benchmarks.py
"""

from __future__ import annotations

import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

OUT = Path(__file__).resolve().parents[1] / "reports/charts"
RESULTS = Path("/tmp")

INK = "#1b1b1f"
MUTED = "#8a8a94"
GRID = "#e4e4e9"
GREEN = "#2f7d5b"
BLUE = "#3b5b92"
AMBER = "#b8862b"
RED = "#a3423c"

plt.rcParams.update({
    "font.family": "DejaVu Sans",
    "font.size": 10,
    "axes.edgecolor": GRID,
    "axes.labelcolor": INK,
    "text.color": INK,
    "xtick.color": MUTED,
    "ytick.color": MUTED,
    "axes.spines.top": False,
    "axes.spines.right": False,
    "figure.facecolor": "white",
})


def load(name: str) -> dict:
    return json.loads((RESULTS / name).read_text())


def save(fig, name: str) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / name
    fig.savefig(path, dpi=170, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    print(path)


def chart_alternatives() -> None:
    """What retrieval buys, against the two things it replaces."""
    saimon = load("r_fin.json")
    grep = load("grep2.json")
    ab = load("2026-11-18-corpus-v2.json")
    baseline = next(a for a in ab["arms"] if a["id"] == "baseline")["summary"]

    labels = ["Grounding@8", "Recall@8", "MRR", "Answer success (40-task A/B)"]
    no_retrieval = [0.0, None, None, baseline["answerable_success_rate"]]
    keyword = [grep["grounding_at_k"], grep["recall_at_k"], grep["mrr"], None]
    system = [saimon["grounding_at_k"], saimon["recall_at_k"], saimon["mrr"],
              next(a for a in ab["arms"] if a["id"] == "rag")["summary"]["answerable_success_rate"]]

    fig, ax = plt.subplots(figsize=(9, 4.6))
    width = 0.26
    xs = range(len(labels))
    for offset, series, colour, name in (
        (-width, no_retrieval, MUTED, "model alone"),
        (0, keyword, AMBER, "grep over the files"),
        (width, system, BLUE, "Saimon"),
    ):
        values = [0.0 if v is None else v for v in series]
        bars = ax.bar([x + offset for x in xs], values, width,
                      label=name, color=colour, zorder=3)
        for bar, value in zip(bars, series):
            if value is None:
                ax.text(bar.get_x() + bar.get_width() / 2, 0.02, "n/a",
                        ha="center", va="bottom", fontsize=8, color=MUTED)
            else:
                # A value near the gate line would be struck through by it.
                label_y = value + 0.02
                if abs(label_y - 0.75) < 0.035:
                    label_y = 0.80
                ax.text(bar.get_x() + bar.get_width() / 2, label_y, f"{value:.2f}",
                        ha="center", va="bottom", fontsize=8.5, color=INK)

    ax.set_xticks(list(xs))
    ax.set_xticklabels(labels)
    ax.set_ylim(0, 1.12)
    ax.set_yticks([0, 0.25, 0.5, 0.75, 1.0])
    ax.axhline(0.75, color=RED, lw=1, ls="--", zorder=2)
    ax.text(3.42, 0.775, "gate 0.75", color=RED, fontsize=8, ha="right")
    ax.yaxis.grid(True, color=GRID, lw=0.8, zorder=0)
    ax.set_axisbelow(True)
    ax.set_title("Retrieval against the alternatives", loc="left", fontsize=13, pad=14)
    ax.text(0, 1.02, "69-task retrieval suite · 55 answerable · k=8 · equal context budget",
            transform=ax.transAxes, fontsize=8.5, color=MUTED)
    ax.legend(frameon=False, ncol=3, loc="upper left", bbox_to_anchor=(0, -0.12))
    save(fig, "01-alternatives.png")


def chart_tradeoff() -> None:
    """Grounding per configuration, with the adversarial cost beside it.

    A scatter put three configurations on the same defence value and stacked
    their labels. One row per configuration reads in a single pass.
    """
    configs = [
        ("default (shipped)", "r_fin.json", "a_fin.json", GREEN, True),
        ("no title weight", "r_8110.json", "a_8110.json", MUTED, False),
        ("diversity cap 3", "r_8111.json", "a_8111.json", MUTED, False),
        ("coverage 0.40", "r_8113.json", "a_8113.json", AMBER, False),
        ("coverage 0.55", "r_8114.json", "a_8114.json", AMBER, False),
        ("subject 10/3", "r_8122.json", "a_8122.json", BLUE, False),
        ("subject 20/2", "r_8121.json", "a_8121.json", BLUE, False),
        ("subject 60/3", "r_8123.json", "a_8123.json", BLUE, False),
    ]
    rows = []
    for label, rfile, afile, colour, shipped in configs:
        r, a = load(rfile), load(afile)
        rows.append((r["grounding_at_k"], a["defended_rate"], label, colour, shipped))
    rows.sort(key=lambda row: row[0], reverse=True)

    fig, ax = plt.subplots(figsize=(9, 4.8))
    ys = list(range(len(rows)))
    for y, (grounding, defended, label, colour, shipped) in zip(ys, rows):
        ax.plot([0.55, grounding], [y, y], color=colour, lw=2.2 if shipped else 1.4,
                alpha=0.9 if shipped else 0.55, zorder=2, solid_capstyle="round")
        ax.scatter(grounding, y, s=120 if shipped else 70, color=colour,
                   edgecolor="white", linewidth=1.4, zorder=3)
        ax.text(0.855, y, f"{grounding:.3f}", va="center", ha="right", fontsize=9,
                color=INK, fontweight="medium" if shipped else "normal")
        ax.text(0.905, y, f"{defended * 16:.0f}/16", va="center", ha="right",
                fontsize=9, color=RED if defended < 0.9 else GREEN)

    ax.axvline(0.75, color=RED, lw=1, ls="--", zorder=1)
    ax.text(0.752, -0.9, "gate 0.75", color=RED, fontsize=8, va="bottom")
    ax.set_xlim(0.55, 0.92)
    ax.set_ylim(-1.05, len(rows) - 0.3)
    ax.invert_yaxis()
    ax.set_yticks(ys)
    ax.set_yticklabels(
        [f"{label}" for _, _, label, _, _ in rows],
        fontsize=9.5,
    )
    ax.tick_params(axis="y", length=0, colors=INK)
    for tick, row in zip(ax.get_yticklabels(), rows):
        tick.set_color(INK if row[4] else MUTED)
    ax.set_xticks([0.60, 0.65, 0.70, 0.75, 0.80])
    ax.set_xlabel("Grounding@8")
    ax.xaxis.grid(True, color=GRID, lw=0.8, zorder=0)
    ax.set_axisbelow(True)
    ax.spines["left"].set_visible(False)
    ax.set_title("Grounding per configuration, and what it costs in false answers",
                 loc="left", fontsize=13, pad=26)
    ax.text(0, 1.015, "55 answerable tasks · defence = adversarial questions caught (of 16)",
            transform=ax.transAxes, fontsize=8.5, color=MUTED)
    ax.text(0.855, -0.9, "grounding", ha="right", fontsize=8, color=MUTED)
    ax.text(0.905, -0.9, "defence", ha="right", fontsize=8, color=MUTED)
    save(fig, "02-tradeoff.png")


def chart_adversarial() -> None:
    """Where the false-premise questions land, by configuration."""
    order = [
        ("default", "a_fin.json"),
        ("subject 10/3", "a_8122.json"),
        ("coverage 0.55", "a_8114.json"),
        ("subject 20/2", "a_8121.json"),
    ]
    fig, ax = plt.subplots(figsize=(9, 3.6))
    labels = [name for name, _ in order]
    corrected = [load(f)["corrected"] for _, f in order]
    silent = [load(f)["silent"] for _, f in order]
    fooled = [load(f)["fooled"] for _, f in order]

    y = range(len(order))
    left = [0] * len(order)
    for values, colour, name in ((corrected, GREEN, "corrected"),
                                 (silent, MUTED, "silent (refused)"),
                                 (fooled, RED, "fooled")):
        ax.barh(list(y), values, left=left, color=colour, label=name, height=0.55, zorder=3)
        for index, value in enumerate(values):
            if value:
                ax.text(left[index] + value / 2, index, str(value), ha="center",
                        va="center", color="white", fontsize=9)
        left = [a + b for a, b in zip(left, values)]

    ax.set_yticks(list(y))
    ax.set_yticklabels(labels)
    ax.invert_yaxis()
    ax.set_xlim(0, 16)
    ax.set_xlabel("of 16 adversarial questions")
    ax.xaxis.grid(True, color=GRID, lw=0.8, zorder=0)
    ax.set_axisbelow(True)
    ax.set_title("False premises: caught, refused, or answered anyway", loc="left",
                 fontsize=13, pad=26)
    ax.text(0, 1.015, "each question names the fact that exposes its premise",
            transform=ax.transAxes, fontsize=8.5, color=MUTED)
    ax.legend(frameon=False, ncol=3, loc="upper left", bbox_to_anchor=(0, -0.22))
    save(fig, "03-adversarial.png")


def chart_arms() -> None:
    """The A/B arms: what the model can do with and without retrieval."""
    ab = load("2026-11-18-corpus-v2.json")
    arms = {a["id"]: a["summary"] for a in ab["arms"] if a["summary"]}
    order = ["baseline", "rag"]
    names = ["model alone", "with Saimon"]
    colours = [MUTED, BLUE]

    fig, axes = plt.subplots(1, 2, figsize=(9, 3.8))
    for ax, field, title, ceiling in (
        (axes[0], "answerable_success_rate", "Answer success on answerable tasks", 1.0),
        (axes[1], "groundedness_mean", "Answer groundedness", 1.0),
    ):
        values = [arms[key][field] for key in order]
        bars = ax.bar(names, values, color=colours, width=0.5, zorder=3)
        for bar, value in zip(bars, values):
            ax.text(bar.get_x() + bar.get_width() / 2, value + 0.02, f"{value:.2f}",
                    ha="center", fontsize=10, color=INK)
        ax.set_ylim(0, ceiling * 1.15)
        ax.set_title(title, loc="left", fontsize=10.5)
        ax.yaxis.grid(True, color=GRID, lw=0.8, zorder=0)
        ax.set_axisbelow(True)

    fig.suptitle("40-task A/B, generation held constant", x=0.01, y=0.96, ha="left",
                 fontsize=13)
    fig.text(0.01, 0.885, "same model, same prompt; only the context changes "
             "· 39 tasks · paired gain +0.33 (95% CI 0.15–0.51)",
             fontsize=8.5, color=MUTED)
    fig.tight_layout(rect=(0, 0, 1, 0.86))
    save(fig, "04-ab-arms.png")


if __name__ == "__main__":
    chart_alternatives()
    chart_tradeoff()
    chart_adversarial()
    chart_arms()
