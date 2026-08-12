"""Query the runbook index and expose retrieval as Prometheus metrics.

Every search is instrumented the same way the host metrics are: a latency
histogram, a counter, and a gauge for the score of the best hit. Retrieval
quality degrades quietly — a search that returns something plausible but wrong
looks identical to a good one from the outside — so the top score being
observable over time is what makes a regression visible at all.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass

import numpy as np
from prometheus_client import Counter, Gauge, Histogram

from app.rag import index as index_module
from app.rag.backends import get_backend

QUERIES = Counter("rag_queries_total", "Runbook searches served", ["outcome"], registry=None)
LATENCY = Histogram(
    "rag_query_duration_seconds",
    "Time to embed a query and rank the corpus",
    buckets=(0.001, 0.0025, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0),
    registry=None,
)
TOP_SCORE = Gauge("rag_top_score", "Similarity of the best hit on the last query", registry=None)
INDEX_DOCS = Gauge("rag_index_documents", "Runbooks in the loaded index", registry=None)
INDEX_CHUNKS = Gauge("rag_index_chunks", "Chunks in the loaded index", registry=None)
INDEX_STALE = Gauge(
    "rag_index_stale", "1 when the corpus has changed since indexing", registry=None
)


_registered: set[int] = set()


def register(registry) -> None:
    """Attach the retrieval metrics to the application registry.

    Idempotent: create_app() runs once at import and again per test, and
    prometheus_client raises on a duplicate collector rather than ignoring it.
    """
    if id(registry) in _registered:
        return
    for metric in (QUERIES, LATENCY, TOP_SCORE, INDEX_DOCS, INDEX_CHUNKS, INDEX_STALE):
        registry.register(metric)
    _registered.add(id(registry))


@dataclass(frozen=True)
class Hit:
    chunk_id: str
    doc_id: str
    title: str
    section: str
    text: str
    score: float

    def as_dict(self) -> dict:
        return {
            "chunk_id": self.chunk_id,
            "doc_id": self.doc_id,
            "title": self.title,
            "section": self.section,
            "score": round(self.score, 4),
            "excerpt": self.text[:320].rstrip() + ("…" if len(self.text) > 320 else ""),
        }


class Searcher:
    """Holds the index and its backend. Thread-safe for concurrent queries."""

    #: Below this cosine similarity a hit is not worth showing at all.
    MIN_RELEVANCE = 0.08
    #: Below this, results are shown but flagged as unreliable.
    CONFIDENCE_THRESHOLD = 0.35

    def __init__(self, idx: index_module.Index) -> None:
        self.index = idx
        self.backend = get_backend(idx.backend_name)
        self.backend.load_state(idx.backend_state)
        self._lock = threading.Lock()
        INDEX_DOCS.set(idx.document_count)
        INDEX_CHUNKS.set(idx.chunk_count)
        INDEX_STALE.set(1 if index_module.is_stale(idx) else 0)

    @classmethod
    def from_disk(cls, path=None) -> Searcher:
        return cls(index_module.load(path))

    def search(self, query: str, k: int = 5, min_score: float = 0.0) -> list[Hit]:
        query = (query or "").strip()
        if not query:
            QUERIES.labels(outcome="empty").inc()
            return []

        start = time.perf_counter()
        with self._lock:
            vector = self.backend.encode([query])[0]
        # Vectors are L2-normalised at build and encode time, so the dot product
        # is already the cosine similarity — no division needed per query.
        scores = self.index.vectors @ vector

        k = max(1, min(k, len(scores)))
        top = np.argpartition(-scores, k - 1)[:k]
        top = top[np.argsort(-scores[top])]

        hits = [
            Hit(
                chunk_id=self.index.chunks[i].chunk_id,
                doc_id=self.index.chunks[i].doc_id,
                title=self.index.chunks[i].title,
                section=self.index.chunks[i].section,
                text=self.index.chunks[i].text,
                score=float(scores[i]),
            )
            for i in top
            if scores[i] >= min_score
        ]

        LATENCY.observe(time.perf_counter() - start)
        QUERIES.labels(outcome="hit" if hits else "miss").inc()
        TOP_SCORE.set(hits[0].score if hits else 0.0)
        return hits

    def triage(self, alert: str, detail: str = "", k: int = 3) -> dict:
        """Rank runbooks for an alert, and surface the Resolution section first.

        Deduplicated to one entry per runbook: three sections of the same
        document is not three answers, and an on-call engineer reading this at
        03:00 wants distinct options.
        """
        query = f"{alert} {detail}".strip()
        # A floor, not just a top-k: without it the tail of the ranking is
        # padded with zero-similarity runbooks, and a suggestion scoring 0.0
        # during an incident is noise an on-call engineer has to read past.
        hits = self.search(query, k=k * 4, min_score=self.MIN_RELEVANCE)

        seen: set[str] = set()
        ranked: list[dict] = []
        for hit in hits:
            if hit.doc_id in seen:
                continue
            seen.add(hit.doc_id)
            resolution = next(
                (
                    c.text
                    for c in self.index.chunks
                    if c.doc_id == hit.doc_id and c.section.lower() == "resolution"
                ),
                None,
            )
            entry = hit.as_dict()
            entry["suggested_action"] = resolution or hit.text
            ranked.append(entry)
            if len(ranked) == k:
                break

        confident = bool(ranked) and ranked[0]["score"] >= self.CONFIDENCE_THRESHOLD
        return {
            "query": query,
            "confident": confident,
            "runbooks": ranked,
            # Saying "I do not know" is a feature. A low-confidence guess during
            # an incident is worse than no answer, because it is acted on.
            "note": None
            if confident
            else "No strong match. Treat these as weak suggestions and escalate.",
        }
