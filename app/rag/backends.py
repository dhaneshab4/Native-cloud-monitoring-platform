"""Pluggable embedding backends.

Two are provided, and the choice between them is deliberately an empirical one
rather than a matter of taste — ``eval/run_eval.py`` scores both against the
same golden set.

``lsa``
    TF-IDF with truncated SVD, implemented in numpy alone. Latent semantic
    analysis: not a transformer, but it does place related terms near each
    other, and it adds nothing to the runtime image beyond numpy.

``transformer``
    sentence-transformers. Better retrieval on paraphrased queries, at the cost
    of pulling torch into the image — roughly two orders of magnitude more
    dependency weight. Only worth it if the eval numbers justify it, which is
    the point of measuring.

The serving path only ever calls ``encode``. Fitting happens offline, in CI.
"""

from __future__ import annotations

import re
from typing import Protocol

import numpy as np

# Deliberately small: a domain stopword list, not a general English one. Words
# like "error" and "check" appear in nearly every runbook and carry no signal
# here, while ordinary English stopwords are already handled by IDF.
_STOPWORDS = frozenset(
    [
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "been",
        "but",
        "by",
        "can",
        "for",
        "from",
        "had",
        "has",
        "have",
        "if",
        "in",
        "into",
        "is",
        "it",
        "its",
        "may",
        "not",
        "of",
        "on",
        "or",
        "our",
        "shall",
        "so",
        "than",
        "that",
        "the",
        "their",
        "them",
        "then",
        "there",
        "these",
        "they",
        "this",
        "to",
        "too",
        "very",
        "was",
        "were",
        "what",
        "when",
        "where",
        "which",
        "while",
        "who",
        "will",
        "with",
        "would",
        "you",
        "your",
    ]
)

_TOKEN = re.compile(r"[a-z][a-z0-9_]{1,}")


def tokenize(text: str) -> list[str]:
    return [t for t in _TOKEN.findall(text.lower()) if t not in _STOPWORDS]


def l2_normalise(matrix: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    return matrix / np.maximum(norms, 1e-12)


class Backend(Protocol):
    name: str

    def fit(self, texts: list[str]) -> None: ...
    def encode(self, texts: list[str]) -> np.ndarray: ...
    def state(self) -> dict: ...
    def load_state(self, state: dict) -> None: ...


class LsaBackend:
    """TF-IDF + truncated SVD, numpy only."""

    name = "lsa"

    def __init__(self, dimensions: int = 96) -> None:
        self.dimensions = dimensions
        self.vocabulary: dict[str, int] = {}
        self.idf: np.ndarray = np.empty(0)
        self.components: np.ndarray = np.empty((0, 0))

    # ------------------------------------------------------------------ fit
    def fit(self, texts: list[str]) -> None:
        docs = [tokenize(t) for t in texts]
        vocab = sorted({term for doc in docs for term in doc})
        self.vocabulary = {term: i for i, term in enumerate(vocab)}

        counts = self._counts(docs)
        n_docs = counts.shape[0]
        document_frequency = (counts > 0).sum(axis=0)
        # Smoothed IDF: the +1s keep a term that appears in every document from
        # collapsing to exactly zero weight.
        self.idf = np.log((1.0 + n_docs) / (1.0 + document_frequency)) + 1.0

        tfidf = l2_normalise(self._sublinear(counts) * self.idf)

        # Full SVD is affordable here: the corpus is tens of documents, not
        # millions. Truncating afterwards avoids a sparse solver dependency.
        _, _, vt = np.linalg.svd(tfidf, full_matrices=False)
        k = min(self.dimensions, vt.shape[0])
        self.components = vt[:k]

    # -------------------------------------------------------------- encode
    def encode(self, texts: list[str]) -> np.ndarray:
        if not self.vocabulary:
            raise RuntimeError("LsaBackend used before fit() or load_state()")
        counts = self._counts([tokenize(t) for t in texts])
        tfidf = l2_normalise(self._sublinear(counts) * self.idf)
        return l2_normalise(tfidf @ self.components.T)

    # ------------------------------------------------------------ internals
    def _counts(self, docs: list[list[str]]) -> np.ndarray:
        matrix = np.zeros((len(docs), len(self.vocabulary)), dtype=np.float64)
        for row, doc in enumerate(docs):
            for term in doc:
                column = self.vocabulary.get(term)
                if column is not None:
                    matrix[row, column] += 1.0
        return matrix

    @staticmethod
    def _sublinear(counts: np.ndarray) -> np.ndarray:
        """1 + log(tf): the tenth mention of a word is not ten times the signal."""
        return np.where(counts > 0, 1.0 + np.log(np.maximum(counts, 1.0)), 0.0)

    # ----------------------------------------------------------- persistence
    def state(self) -> dict:
        return {
            "vocabulary": np.array(list(self.vocabulary.keys()), dtype=object),
            "idf": self.idf,
            "components": self.components,
            "dimensions": np.array([self.dimensions]),
        }

    def load_state(self, state: dict) -> None:
        terms = list(state["vocabulary"])
        self.vocabulary = {str(t): i for i, t in enumerate(terms)}
        self.idf = np.asarray(state["idf"], dtype=np.float64)
        self.components = np.asarray(state["components"], dtype=np.float64)
        self.dimensions = int(np.asarray(state["dimensions"]).ravel()[0])


class TransformerBackend:
    """sentence-transformers, loaded lazily so torch is never imported unless used."""

    name = "transformer"

    def __init__(self, model_name: str = "sentence-transformers/all-MiniLM-L6-v2") -> None:
        self.model_name = model_name
        self._model = None

    def _load(self):
        if self._model is None:
            from sentence_transformers import SentenceTransformer

            self._model = SentenceTransformer(self.model_name)
        return self._model

    def fit(self, texts: list[str]) -> None:
        """Pretrained: nothing to fit. Loaded eagerly so failures surface at build."""
        self._load()

    def encode(self, texts: list[str]) -> np.ndarray:
        vectors = self._load().encode(texts, convert_to_numpy=True, show_progress_bar=False)
        return l2_normalise(np.asarray(vectors, dtype=np.float64))

    def state(self) -> dict:
        return {"model_name": np.array([self.model_name], dtype=object)}

    def load_state(self, state: dict) -> None:
        self.model_name = str(np.asarray(state["model_name"]).ravel()[0])
        self._model = None


def get_backend(name: str) -> Backend:
    if name == "lsa":
        return LsaBackend()
    if name == "transformer":
        return TransformerBackend()
    raise ValueError(f"unknown backend {name!r}; expected 'lsa' or 'transformer'")
