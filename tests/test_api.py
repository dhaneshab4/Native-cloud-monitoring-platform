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
