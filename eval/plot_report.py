"""Render eval/report.json as a comparison chart.

Written as a script rather than a notebook so it runs in CI and the image can
be attached to a run, a PR, or a README.
"""

from __future__ import annotations

import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

REPORT = Path(__file__).with_name("report.json")
OUT = Path(__file__).with_name("retrieval-quality.png")

INK = "#1f2937"
MUTED = "#6b7280"
COLOURS = {"lsa": "#2563eb", "transformer": "#f59e0b"}


def main() -> None:
    results = json.loads(REPORT.read_text())["results"]
    names = [r["backend"] for r in results]

    fig, axes = plt.subplots(1, 3, figsize=(13, 4.4), facecolor="white")
    fig.suptitle(
        "Runbook retrieval: is a transformer worth the weight?",
        fontsize=14,
        fontweight="bold",
        color=INK,
        x=0.5,
        y=0.985,
    )

    # ---------------------------------------------------------- quality bars
    ax = axes[0]
    metrics = ["recall@1", "recall@3", "recall@5"]
    width = 0.36
    for i, r in enumerate(results):
        xs = [x + (i - 0.5) * width for x in range(len(metrics))]
        vals = [r[m] * 100 for m in metrics]
        bars = ax.bar(xs, vals, width, label=r["backend"], color=COLOURS.get(r["backend"], MUTED))
        for b, v in zip(bars, vals, strict=True):
            ax.text(
                b.get_x() + b.get_width() / 2,
                v + 1.5,
                f"{v:.0f}%",
                ha="center",
                fontsize=9,
                color=INK,
            )
    ax.set_xticks(range(len(metrics)), metrics)
    ax.set_ylim(0, 112)
    ax.set_ylabel("correct runbook retrieved (%)")
    ax.set_title("Quality", fontsize=11, color=INK, pad=8)

    # ------------------------------------------------------------------ MRR
    ax = axes[1]
    vals = [r["mrr"] for r in results]
    bars = ax.bar(names, vals, 0.5, color=[COLOURS.get(n, MUTED) for n in names])
    for b, v in zip(bars, vals, strict=True):
        ax.text(
            b.get_x() + b.get_width() / 2,
            v + 0.015,
            f"{v:.3f}",
            ha="center",
            fontsize=10,
            color=INK,
        )
    ax.set_ylim(0, 1.12)
    ax.set_ylabel("mean reciprocal rank")
    ax.set_title("Ranking", fontsize=11, color=INK, pad=8)

    # -------------------------------------------------------------- latency
    ax = axes[2]
    vals = [r["latency_ms_p95"] for r in results]
    bars = ax.bar(names, vals, 0.5, color=[COLOURS.get(n, MUTED) for n in names])
    ax.set_yscale("log")
    for b, v in zip(bars, vals, strict=True):
        ax.text(
            b.get_x() + b.get_width() / 2,
            v * 1.25,
            f"{v:.2f} ms",
            ha="center",
            fontsize=10,
            color=INK,
        )
    ax.set_ylim(0.01, max(vals) * 12)
    ax.set_ylabel("p95 query latency (ms, log scale)")
    ax.set_title("Cost", fontsize=11, color=INK, pad=8)

    for ax in axes:
        ax.spines[["top", "right"]].set_visible(False)
        ax.spines[["left", "bottom"]].set_color("#d1d5db")
        ax.tick_params(colors=MUTED, labelsize=9)
        ax.grid(axis="y", color="#eef1f5", linewidth=1)
        ax.set_axisbelow(True)

    if len(results) == 2:
        lsa = next(r for r in results if r["backend"] == "lsa")
        tr = next(r for r in results if r["backend"] == "transformer")
        factor = tr["latency_ms_p95"] / max(lsa["latency_ms_p95"], 1e-9)
        delta = (tr["recall@1"] - lsa["recall@1"]) * 100
        fig.text(
            0.5,
            0.015,
            f"Identical recall@3. The transformer buys {delta:+.1f} points of recall@1 "
            f"for {factor:,.0f}x the p95 latency and ~2 GB of image weight. "
            "Shipping LSA.",
            ha="center",
            fontsize=10,
            color=INK,
        )

    handles = [plt.Rectangle((0, 0), 1, 1, color=COLOURS.get(n, MUTED)) for n in names]
    fig.legend(
        handles,
        names,
        ncols=len(names),
        frameon=False,
        fontsize=10,
        loc="upper center",
        bbox_to_anchor=(0.5, 0.945),
    )

    fig.tight_layout(rect=(0, 0.05, 1, 0.90))
    fig.savefig(OUT, dpi=160)
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
