"""Build, persist and load the search index as a versioned artefact.

The index is treated the same way as a container image: built once in CI,
checksummed, and consumed by the runtime rather than regenerated at boot.
Startup stays fast and, more importantly, what was tested is what serves —
rebuilding on every start would mean the artefact CI measured is not the one
answering queries.

The corpus fingerprint is stored alongside it, so a stale index is a detectable
condition rather than a silently wrong answer.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from app.rag import corpus
from app.rag.backends import get_backend

DEFAULT_INDEX = Path(__file__).resolve().parents[2] / "data" / "index.npz"
SCHEMA_VERSION = 1


@dataclass(frozen=True)
class Index:
    backend_name: str
    vectors: np.ndarray
    chunks: list[corpus.Chunk]
    corpus_fingerprint: str
    checksum: str
    backend_state: dict

    @property
    def document_count(self) -> int:
        return len({c.doc_id for c in self.chunks})

    @property
    def chunk_count(self) -> int:
        return len(self.chunks)


def _checksum(vectors: np.ndarray, ids: list[str]) -> str:
    h = hashlib.sha256()
    h.update(np.ascontiguousarray(vectors, dtype=np.float64).tobytes())
    h.update("\x00".join(ids).encode())
    return h.hexdigest()[:16]


def build(backend_name: str = "lsa", corpus_dir: Path | None = None) -> Index:
    chunks = corpus.load(corpus_dir)
    backend = get_backend(backend_name)
    texts = [c.embed_text for c in chunks]
    backend.fit(texts)
    vectors = backend.encode(texts)
    ids = [c.chunk_id for c in chunks]
    return Index(
        backend_name=backend.name,
        vectors=vectors,
        chunks=chunks,
        corpus_fingerprint=corpus.fingerprint(corpus_dir),
        checksum=_checksum(vectors, ids),
        backend_state=backend.state(),
    )


def save(index: Index, path: Path | None = None) -> Path:
    target = Path(path or DEFAULT_INDEX)
    target.parent.mkdir(parents=True, exist_ok=True)
    meta = {
        "schema_version": SCHEMA_VERSION,
        "backend": index.backend_name,
        "corpus_fingerprint": index.corpus_fingerprint,
        "checksum": index.checksum,
        "chunks": [
            {
                "chunk_id": c.chunk_id,
                "doc_id": c.doc_id,
                "title": c.title,
                "section": c.section,
                "text": c.text,
            }
            for c in index.chunks
        ],
    }
    np.savez_compressed(
        target,
        vectors=index.vectors,
        meta=np.array([json.dumps(meta)], dtype=object),
        **{f"backend__{k}": v for k, v in index.backend_state.items()},
    )
    return target


def load(path: Path | None = None) -> Index:
    source = Path(path or DEFAULT_INDEX)
    if not source.exists():
        raise FileNotFoundError(
            f"no index at {source}. Build one with: python -m app.rag.index build"
        )
    with np.load(source, allow_pickle=True) as data:
        meta = json.loads(str(data["meta"][0]))
        if meta.get("schema_version") != SCHEMA_VERSION:
            raise ValueError(
                f"index schema {meta.get('schema_version')} != "
                f"expected {SCHEMA_VERSION}; rebuild it"
            )
        vectors = np.asarray(data["vectors"], dtype=np.float64)
        backend_state = {
            k.removeprefix("backend__"): data[k] for k in data.files if k.startswith("backend__")
        }
    chunks = [
        corpus.Chunk(c["chunk_id"], c["doc_id"], c["title"], c["section"], c["text"])
        for c in meta["chunks"]
    ]
    recomputed = _checksum(vectors, [c.chunk_id for c in chunks])
    if recomputed != meta["checksum"]:
        raise ValueError(
            f"index checksum mismatch: file says {meta['checksum']}, content is {recomputed}"
        )
    return Index(
        backend_name=meta["backend"],
        vectors=vectors,
        chunks=chunks,
        corpus_fingerprint=meta["corpus_fingerprint"],
        checksum=meta["checksum"],
        backend_state=backend_state,
    )


def is_stale(index: Index, corpus_dir: Path | None = None) -> bool:
    """True when the runbooks have changed since the index was built."""
    return index.corpus_fingerprint != corpus.fingerprint(corpus_dir)


def _cli() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Build the runbook search index")
    parser.add_argument("command", choices=["build", "inspect"])
    parser.add_argument("--backend", default="lsa", choices=["lsa", "transformer"])
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args()

    if args.command == "build":
        index = build(args.backend)
        path = save(index, args.out)
        print(f"backend      {index.backend_name}")
        print(f"documents    {index.document_count}")
        print(f"chunks       {index.chunk_count}")
        print(f"dimensions   {index.vectors.shape[1]}")
        print(f"fingerprint  {index.corpus_fingerprint}")
        print(f"checksum     {index.checksum}")
        print(f"written      {path} ({path.stat().st_size / 1024:.1f} KiB)")
    else:
        index = load(args.out)
        print(f"backend      {index.backend_name}")
        print(f"documents    {index.document_count}")
        print(f"chunks       {index.chunk_count}")
        print(f"checksum     {index.checksum}")
        print(f"stale        {is_stale(index)}")


if __name__ == "__main__":
    _cli()
