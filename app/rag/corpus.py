"""Load the runbook corpus and split it into retrievable chunks.

Chunking is by markdown section rather than by fixed token count. Runbooks are
already written as Symptoms / Diagnosis / Resolution, so the author's own
structure is a better boundary than an arbitrary window, and it means a hit can
be attributed to a specific part of a document.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path

DEFAULT_CORPUS = Path(__file__).resolve().parents[2] / "deploy" / "runbooks"

_HEADING = re.compile(r"^##\s+(.*)$", re.MULTILINE)
_TITLE = re.compile(r"^#\s+(.*)$", re.MULTILINE)


@dataclass(frozen=True)
class Chunk:
    chunk_id: str
    doc_id: str
    title: str
    section: str
    text: str

    @property
    def embed_text(self) -> str:
        """Title and section are prepended so they carry retrieval weight."""
        return f"{self.title}. {self.section}. {self.text}"


def _split(path: Path) -> list[Chunk]:
    raw = path.read_text(encoding="utf-8")
    doc_id = path.stem
    title_match = _TITLE.search(raw)
    title = title_match.group(1).strip() if title_match else doc_id

    headings = list(_HEADING.finditer(raw))
    if not headings:
        return [Chunk(doc_id, doc_id, title, "body", raw.strip())]

    # Text before the first ## is the preamble: alert metadata, severity, etc.
    chunks = []
    preamble = raw[: headings[0].start()]
    preamble = _TITLE.sub("", preamble).strip()
    if preamble:
        chunks.append(Chunk(f"{doc_id}#overview", doc_id, title, "Overview", preamble))

    for i, h in enumerate(headings):
        end = headings[i + 1].start() if i + 1 < len(headings) else len(raw)
        section = h.group(1).strip()
        body = raw[h.end() : end].strip()
        if body:
            chunks.append(Chunk(f"{doc_id}#{section.lower()}", doc_id, title, section, body))
    return chunks


def load(corpus_dir: Path | None = None) -> list[Chunk]:
    """Read every runbook, in a stable order so the index is reproducible."""
    directory = Path(corpus_dir or DEFAULT_CORPUS)
    if not directory.is_dir():
        raise FileNotFoundError(f"corpus directory not found: {directory}")
    chunks: list[Chunk] = []
    for path in sorted(directory.glob("*.md")):
        chunks.extend(_split(path))
    if not chunks:
        raise ValueError(f"no runbooks found in {directory}")
    return chunks


def fingerprint(corpus_dir: Path | None = None) -> str:
    """Content hash of the corpus, so a stale index can be detected."""
    directory = Path(corpus_dir or DEFAULT_CORPUS)
    h = hashlib.sha256()
    for path in sorted(directory.glob("*.md")):
        h.update(path.name.encode())
        h.update(path.read_bytes())
    return h.hexdigest()[:16]
