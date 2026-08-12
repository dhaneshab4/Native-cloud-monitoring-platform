"""Measure runbook retrieval quality and fail the build when it regresses.

This is the coverage gate applied to a model instead of to code. `pytest
--cov-fail-under=90` stops untested code reaching main; `run_eval.py
--fail-under-recall3` stops a retrieval regression reaching main. Both answer
the same question — is this worse than what we already had — and neither is
answerable by looking at the diff.

Reported metrics:

  recall@k   fraction of queries where the right runbook appears in the top k.
             recall@1 is what a user experiences; recall@3 is what a user
             tolerates when they can see three options at once.
  MRR        mean reciprocal rank. Rewards being right *and* being first, so a
             change that keeps recall flat while pushing correct answers down
             the list still shows up.
  p95        the slow tail, not the average. Retrieval that is usually fast and
             occasionally not is still a bad experience.

Usage:
    python -m eval.run_eval --backend lsa --fail-under-recall3 0.85
    python -m eval.run_eval --compare          # score every backend
"""

from __future__ import annotations

import argparse
import json
import math
import statistics
import sys
import time
from pathlib import Path

from app.rag import index as index_module
from app.rag.search import Searcher

GOLDEN = Path(__file__).with_name("golden.json")
REPORT = Path(__file__).with_name("report.json")
MAX_K = 5


def _percentile(values: list[float], q: float) -> float:
    """Nearest-rank percentile. ceil(q*n) rather than int(q*n) — with 33 samples
    the latter picks the 31st value and calls it the 95th percentile."""
    ordered = sorted(values)
    rank = max(1, math.ceil(q * len(ordered)))
    return ordered[rank - 1]


def load_cases(path: Path = GOLDEN) -> list[dict]:
    data = json.loads(path.read_text(encoding="utf-8"))
    cases = data["cases"]
    if not cases:
        raise ValueError("golden set is empty")
    return cases


def evaluate(backend_name: str, cases: list[dict]) -> dict:
    index = index_module.build(backend_name)
    searcher = Searcher(index)

    # One untimed warm-up. The first transformer query pays for model load and
    # lazy kernel init, which is a one-off startup cost, not a per-query one.
    # Leaving it in produced a mean above the p95 — a clear sign the average was
    # measuring something other than steady-state latency.
    searcher.search("warm up the backend", k=1)

    ranks: list[int | None] = []
    latencies: list[float] = []
    failures: list[dict] = []
    retrieved_per_case: list[list[str]] = []

    for case in cases:
        start = time.perf_counter()
        hits = searcher.search(case["query"], k=MAX_K * 3)
        latencies.append((time.perf_counter() - start) * 1000)

        # Chunk hits collapse to their document, keeping first appearance order.
        ordered: list[str] = []
        for hit in hits:
            if hit.doc_id not in ordered:
                ordered.append(hit.doc_id)

        retrieved_per_case.append(ordered[:MAX_K])
        rank = ordered.index(case["expect"]) + 1 if case["expect"] in ordered else None
        ranks.append(rank)
        if rank is None or rank > 3:
            failures.append(
                {
                    "query": case["query"],
                    "expected": case["expect"],
                    "rank": rank,
                    "got": ordered[:3],
                }
            )

    # Which runbooks never surface for any query? Either nobody would ever ask
    # for them, or they are written in language no one uses. Both are content
    # problems the retrieval numbers alone will not show.
    retrieved = {d for hit_ids in retrieved_per_case for d in hit_ids}
    all_docs = {c.doc_id for c in index.chunks}
    unreachable = sorted(all_docs - retrieved)

    total = len(cases)
    recall = {
        f"recall@{k}": sum(1 for r in ranks if r is not None and r <= k) / total for k in (1, 3, 5)
    }
    mrr = sum(1.0 / r for r in ranks if r is not None) / total

    return {
        "backend": backend_name,
        "cases": total,
        "documents": index.document_count,
        "chunks": index.chunk_count,
        **{k: round(v, 4) for k, v in recall.items()},
        "mrr": round(mrr, 4),
        "latency_ms_mean": round(statistics.mean(latencies), 3),
        "latency_ms_median": round(statistics.median(latencies), 3),
        "latency_ms_p95": round(_percentile(latencies, 0.95), 3),
        "unreachable_runbooks": unreachable,
        "failures": failures,
    }


def render(result: dict) -> str:
    lines = [
        f"backend            {result['backend']}",
        f"corpus             {result['documents']} runbooks, {result['chunks']} chunks",
        f"queries            {result['cases']}",
        f"recall@1           {result['recall@1']:.1%}",
        f"recall@3           {result['recall@3']:.1%}",
        f"recall@5           {result['recall@5']:.1%}",
        f"MRR                {result['mrr']:.4f}",
        f"latency med/mean/p95  {result['latency_ms_median']:.2f} / "
        f"{result['latency_ms_mean']:.2f} / {result['latency_ms_p95']:.2f} ms",
    ]
    if result["unreachable_runbooks"]:
        lines.append("\nnever retrieved by any query: " + ", ".join(result["unreachable_runbooks"]))
    if result["failures"]:
        lines.append(f"\nmissed the top 3 ({len(result['failures'])}):")
        for f in result["failures"]:
            got = ", ".join(f["got"]) or "nothing"
            rank = f"rank {f['rank']}" if f["rank"] else "not retrieved"
            lines.append(f"  {f['query']}")
            lines.append(f"      wanted {f['expected']} ({rank}) — got {got}")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backend", default="lsa", choices=["lsa", "transformer"])
    parser.add_argument("--compare", action="store_true", help="score every backend")
    parser.add_argument("--fail-under-recall3", type=float, default=None)
    parser.add_argument("--fail-under-mrr", type=float, default=None)
    parser.add_argument("--report", type=Path, default=REPORT)
    args = parser.parse_args()

    cases = load_cases()
    backends = ["lsa", "transformer"] if args.compare else [args.backend]

    results = []
    for name in backends:
        try:
            result = evaluate(name, cases)
        except ImportError as exc:
            print(f"skipping {name}: {exc}", file=sys.stderr)
            continue
        results.append(result)
        print(render(result))
        print()

    if not results:
        print("no backend could be evaluated", file=sys.stderr)
        return 1

    args.report.write_text(json.dumps({"results": results}, indent=2) + "\n", encoding="utf-8")
    print(f"report written to {args.report}")

    if args.compare and len(results) > 1:
        best = max(results, key=lambda r: r["mrr"])
        print(f"\nbest MRR: {best['backend']} ({best['mrr']:.4f})")

    primary = results[0]
    failed = False
    if args.fail_under_recall3 is not None and primary["recall@3"] < args.fail_under_recall3:
        print(
            f"\nFAIL recall@3 {primary['recall@3']:.1%} below floor {args.fail_under_recall3:.1%}",
            file=sys.stderr,
        )
        failed = True
    if args.fail_under_mrr is not None and primary["mrr"] < args.fail_under_mrr:
        print(
            f"\nFAIL MRR {primary['mrr']:.4f} below floor {args.fail_under_mrr:.4f}",
            file=sys.stderr,
        )
        failed = True
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
