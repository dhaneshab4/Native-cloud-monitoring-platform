"""Tests for the runbook corpus, index artefact and retrieval."""

import json

import numpy as np
import pytest

from app.rag import corpus
from app.rag import index as index_module
from app.rag.backends import LsaBackend, get_backend, l2_normalise, tokenize
from app.rag.search import Searcher


# ------------------------------------------------------------------- corpus
def test_corpus_loads_every_runbook():
    chunks = corpus.load()
    docs = {c.doc_id for c in chunks}
    assert len(docs) >= 10
    assert "disk-full" in docs
    assert len(chunks) > len(docs), "each runbook should split into several sections"


def test_chunks_carry_title_and_section():
    chunk = next(c for c in corpus.load() if c.doc_id == "disk-full")
    assert chunk.title
    assert chunk.section
    assert chunk.title in chunk.embed_text
    assert chunk.section in chunk.embed_text


def test_fingerprint_is_stable_and_content_dependent(tmp_path):
    first = corpus.fingerprint()
    assert first == corpus.fingerprint()

    (tmp_path / "a.md").write_text("# A\n\n## Symptoms\n\nsomething broke\n")
    before = corpus.fingerprint(tmp_path)
    (tmp_path / "a.md").write_text("# A\n\n## Symptoms\n\nsomething else broke\n")
    assert corpus.fingerprint(tmp_path) != before


def test_missing_corpus_directory_is_an_error(tmp_path):
    with pytest.raises(FileNotFoundError):
        corpus.load(tmp_path / "nope")


def test_empty_corpus_directory_is_an_error(tmp_path):
    with pytest.raises(ValueError, match="no runbooks"):
        corpus.load(tmp_path)


# ------------------------------------------------------------------ backends
def test_tokenizer_drops_stopwords_and_punctuation():
    tokens = tokenize("The disk is FULL, and writes are failing!")
    assert "the" not in tokens
    assert "disk" in tokens
    assert "full" in tokens
    assert all(t.isalnum() or "_" in t for t in tokens)


def test_l2_normalise_handles_a_zero_row():
    out = l2_normalise(np.array([[3.0, 4.0], [0.0, 0.0]]))
    assert out[0] == pytest.approx([0.6, 0.8])
    assert not np.isnan(out[1]).any(), "a zero vector must not produce NaN"


def test_lsa_vectors_are_unit_length():
    backend = LsaBackend(dimensions=8)
    backend.fit(["disk is full", "memory is leaking", "cpu is saturated"])
    vectors = backend.encode(["the disk filled up"])
    assert np.linalg.norm(vectors[0]) == pytest.approx(1.0, abs=1e-9)


def test_lsa_ranks_a_related_query_above_an_unrelated_one():
    backend = LsaBackend(dimensions=8)
    texts = ["disk full no space left on device", "rotate the leaked api token"]
    backend.fit(texts)
    corpus_vectors = backend.encode(texts)
    query = backend.encode(["ran out of storage space"])[0]
    scores = corpus_vectors @ query
    assert scores[0] > scores[1]


def test_lsa_survives_a_round_trip_through_its_state():
    original = LsaBackend(dimensions=8)
    texts = ["disk full", "memory leak", "cpu saturated"]
    original.fit(texts)
    expected = original.encode(["disk"])

    restored = LsaBackend()
    restored.load_state(original.state())
    assert restored.encode(["disk"]) == pytest.approx(expected)


def test_encoding_before_fitting_is_an_error():
    with pytest.raises(RuntimeError, match="before fit"):
        LsaBackend().encode(["anything"])


def test_unknown_backend_name_is_rejected():
    with pytest.raises(ValueError, match="unknown backend"):
        get_backend("magic")


# --------------------------------------------------------------------- index
@pytest.fixture(scope="module")
def built_index():
    return index_module.build("lsa")


def test_index_covers_the_whole_corpus(built_index):
    assert built_index.vectors.shape[0] == built_index.chunk_count
    assert built_index.document_count >= 10
    assert built_index.backend_name == "lsa"


def test_index_round_trips_through_disk(tmp_path, built_index):
    path = index_module.save(built_index, tmp_path / "index.npz")
    loaded = index_module.load(path)
    assert loaded.checksum == built_index.checksum
    assert loaded.chunk_count == built_index.chunk_count
    assert loaded.vectors == pytest.approx(built_index.vectors)


def test_tampered_index_is_rejected(tmp_path, built_index):
    path = index_module.save(built_index, tmp_path / "index.npz")
    with np.load(path, allow_pickle=True) as data:
        contents = dict(data)
    contents["vectors"] = contents["vectors"] * 0.5  # same shape, different content
    np.savez_compressed(path, **contents)

    with pytest.raises(ValueError, match="checksum mismatch"):
        index_module.load(path)


def test_index_from_a_future_schema_is_rejected(tmp_path, built_index):
    path = index_module.save(built_index, tmp_path / "index.npz")
    with np.load(path, allow_pickle=True) as data:
        contents = dict(data)
    meta = json.loads(str(contents["meta"][0]))
    meta["schema_version"] = index_module.SCHEMA_VERSION + 1
    contents["meta"] = np.array([json.dumps(meta)], dtype=object)
    np.savez_compressed(path, **contents)

    with pytest.raises(ValueError, match="schema"):
        index_module.load(path)


def test_missing_index_names_the_command_that_builds_it(tmp_path):
    with pytest.raises(FileNotFoundError, match=r"app\.rag\.index build"):
        index_module.load(tmp_path / "absent.npz")


def test_staleness_is_detected(tmp_path, built_index):
    assert not index_module.is_stale(built_index)
    (tmp_path / "new.md").write_text("# New\n\n## Symptoms\n\nunrelated\n")
    assert index_module.is_stale(built_index, tmp_path)


# -------------------------------------------------------------------- search
@pytest.fixture(scope="module")
def searcher(built_index):
    return Searcher(built_index)


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ("no space left on device", "disk-full"),
        ("oom killer terminated the process", "high-memory"),
        ("graphs have flatlined", "target-down"),
        ("a credential was exposed", "secrets-rotation"),
        ("pod stuck in crashloopbackoff", "container-unhealthy"),
    ],
)
def test_retrieval_finds_the_right_runbook(searcher, query, expected):
    hits = searcher.search(query, k=5)
    assert expected in {h.doc_id for h in hits}, f"{query!r} returned {[h.doc_id for h in hits]}"


def test_results_are_ordered_by_descending_score(searcher):
    scores = [h.score for h in searcher.search("disk is full", k=5)]
    assert scores == sorted(scores, reverse=True)


def test_empty_query_returns_nothing(searcher):
    assert searcher.search("   ") == []


def test_k_is_clamped_to_the_corpus_size(searcher):
    assert len(searcher.search("disk", k=10_000)) <= searcher.index.chunk_count


def test_triage_returns_one_entry_per_runbook(searcher):
    result = searcher.triage("DiskAlmostFull", "system_disk_percent 91")
    ids = [r["doc_id"] for r in result["runbooks"]]
    assert len(ids) == len(set(ids)), "the same runbook must not appear twice"
    assert result["runbooks"][0]["doc_id"] == "disk-full"


def test_triage_surfaces_a_suggested_action(searcher):
    result = searcher.triage("HighMemory", "memory at 94 percent")
    assert result["runbooks"][0]["suggested_action"].strip()


def test_triage_refuses_to_guess_on_nonsense(searcher):
    result = searcher.triage("xyzzy plugh frobnicate quux")
    assert result["confident"] is False
    assert result["note"]


def test_triage_never_suggests_an_irrelevant_runbook(searcher):
    """Padding the ranking with zero-similarity hits is worse than a short list."""
    result = searcher.triage("TargetDown", "scrape failed")
    assert all(r["score"] >= Searcher.MIN_RELEVANCE for r in result["runbooks"])
