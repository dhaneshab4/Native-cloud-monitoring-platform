"""Configuration parsing, including the failure modes."""

import dataclasses

import pytest

from app.config import Config, _float_env, _int_env


def test_defaults_apply_when_unset(monkeypatch):
    for var in ("CPU_WARN_PERCENT", "MEM_WARN_PERCENT", "DISK_WARN_PERCENT", "APP_PORT"):
        monkeypatch.delenv(var, raising=False)
    cfg = Config.from_env()
    assert cfg.cpu_warn == 80.0
    assert cfg.port == 5000
    assert cfg.disk_path == "/"


def test_environment_overrides_defaults(monkeypatch):
    monkeypatch.setenv("CPU_WARN_PERCENT", "55.5")
    monkeypatch.setenv("APP_PORT", "8080")
    cfg = Config.from_env()
    assert cfg.cpu_warn == 55.5
    assert cfg.port == 8080


def test_blank_value_falls_back_to_default(monkeypatch):
    monkeypatch.setenv("CPU_WARN_PERCENT", "   ")
    assert _float_env("CPU_WARN_PERCENT", 80.0) == 80.0


@pytest.mark.parametrize("bad", ["abc", "1.2.3", "eighty"])
def test_non_numeric_float_exits_loudly(monkeypatch, bad):
    monkeypatch.setenv("CPU_WARN_PERCENT", bad)
    with pytest.raises(SystemExit, match="must be a number"):
        _float_env("CPU_WARN_PERCENT", 80.0)


def test_non_integer_port_exits_loudly(monkeypatch):
    monkeypatch.setenv("APP_PORT", "not-a-port")
    with pytest.raises(SystemExit, match="must be an integer"):
        _int_env("APP_PORT", 5000)


def test_thresholds_mapping():
    cfg = Config.from_env()
    assert cfg.thresholds() == {
        "cpu": cfg.cpu_warn,
        "memory": cfg.mem_warn,
        "disk": cfg.disk_warn,
    }


def test_config_is_immutable():
    cfg = Config.from_env()
    with pytest.raises(dataclasses.FrozenInstanceError):
        cfg.cpu_warn = 1.0
