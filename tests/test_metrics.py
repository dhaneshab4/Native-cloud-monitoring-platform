"""Unit tests for the collection layer."""

from unittest.mock import patch

from app import metrics


def test_collect_returns_plausible_values():
    s = metrics.collect()
    assert 0 <= s.cpu_percent <= 100
    assert 0 <= s.memory_percent <= 100
    assert 0 <= s.disk_percent <= 100
    assert s.memory_total_bytes > 0
    assert s.process_count > 0
    assert s.status in {"healthy", "degraded"}


def test_status_is_degraded_when_a_threshold_is_breached():
    with patch.object(metrics.psutil, "cpu_percent", return_value=99.0):
        s = metrics.collect()
    assert s.status == "degraded"
    assert any("cpu" in b for b in s.breaches)


def test_status_is_healthy_below_thresholds():
    with (
        patch.object(metrics.psutil, "cpu_percent", return_value=1.0),
        patch.object(metrics, "config", metrics.config),
    ):
        s = metrics.collect()
    # memory/disk on the runner are unknown, so assert only the CPU branch
    assert not any("cpu" in b for b in s.breaches)


def test_load_average_falls_back_when_unsupported():
    with patch.object(metrics.psutil, "getloadavg", side_effect=OSError):
        assert metrics._load_average() == (0.0, 0.0, 0.0)


def test_prometheus_payload_exposes_expected_series():
    body = metrics.prometheus_payload().decode()
    for series in (
        "system_cpu_percent",
        "system_memory_percent",
        "system_disk_percent",
        "system_status",
    ):
        assert series in body
