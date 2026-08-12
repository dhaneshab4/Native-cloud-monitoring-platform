"""Endpoint contract tests."""

from unittest.mock import patch

from app import metrics


def test_index_renders(client):
    r = client.get("/")
    assert r.status_code == 200
    assert b"Cloud Native Monitoring" in r.data


def test_healthz_is_always_ok(client):
    r = client.get("/healthz")
    assert r.status_code == 200
    assert r.get_json()["status"] == "ok"


def test_readyz_ok(client):
    assert client.get("/readyz").status_code == 200


def test_readyz_fails_when_collection_breaks(client):
    with patch("app.main.collect", side_effect=RuntimeError("no /proc")):
        r = client.get("/readyz")
    assert r.status_code == 503
    assert r.get_json()["status"] == "unready"


def test_api_metrics_shape(client):
    d = client.get("/api/metrics").get_json()
    for key in ("cpu_percent", "memory_percent", "disk_percent", "status", "breaches", "host"):
        assert key in d


def test_api_metrics_returns_503_when_degraded(client):
    with patch.object(metrics.psutil, "cpu_percent", return_value=100.0):
        r = client.get("/api/metrics")
    assert r.status_code == 503
    assert r.get_json()["status"] == "degraded"


def test_metrics_endpoint_is_prometheus_text(client):
    r = client.get("/metrics")
    assert r.status_code == 200
    assert r.mimetype == "text/plain"
    assert b"system_cpu_percent" in r.data


def test_unknown_route_is_json_404(client):
    r = client.get("/nope")
    assert r.status_code == 404
    assert r.get_json()["error"] == "not found"


# ------------------------------------------------------- runbook search API
def test_search_requires_a_query(client):
    r = client.get("/api/search")
    assert r.status_code == 400
    assert "q" in r.get_json()["error"]


def test_search_returns_ranked_results(client):
    d = client.get("/api/search?q=no+space+left+on+device&k=3").get_json()
    assert d["count"] >= 1
    assert d["results"][0]["doc_id"] == "disk-full"
    assert "excerpt" in d["results"][0]


def test_search_rejects_a_non_integer_k(client):
    assert client.get("/api/search?q=disk&k=lots").status_code == 400


def test_search_clamps_k(client):
    d = client.get("/api/search?q=disk&k=9999").get_json()
    assert d["count"] <= 20


def test_triage_requires_an_alert(client):
    r = client.post("/api/triage", json={})
    assert r.status_code == 400


def test_triage_ranks_the_matching_runbook_first(client):
    d = client.post("/api/triage", json={"alert": "DiskAlmostFull"}).get_json()
    assert d["confident"] is True
    assert d["runbooks"][0]["doc_id"] == "disk-full"


def test_triage_declines_to_guess(client):
    d = client.post("/api/triage", json={"alert": "xyzzy plugh frobnicate"}).get_json()
    assert d["confident"] is False


def test_retrieval_metrics_are_exported(client):
    client.get("/api/search?q=disk")
    body = client.get("/metrics").data.decode()
    for series in (
        "rag_queries_total",
        "rag_query_duration_seconds",
        "rag_index_documents",
        "rag_top_score",
    ):
        assert series in body
