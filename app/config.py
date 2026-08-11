"""Runtime configuration, read once from the environment at import time.

Every setting has a working default so the app runs with no configuration at
all; the environment is only needed to change behaviour, not to enable it.
Values are read through an explicit ``from_env`` constructor rather than
dataclass field defaults, because field defaults are evaluated at class
definition and that is easy to misread as a per-instance read.
"""

from __future__ import annotations

import os
from dataclasses import dataclass


def _float_env(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return float(raw)
    except ValueError:
        raise SystemExit(f"{name} must be a number, got {raw!r}") from None


def _int_env(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return int(raw)
    except ValueError:
        raise SystemExit(f"{name} must be an integer, got {raw!r}") from None


@dataclass(frozen=True)
class Config:
    host: str
    port: int
    cpu_warn: float
    mem_warn: float
    disk_warn: float
    sample_interval: float
    disk_path: str

    @classmethod
    def from_env(cls) -> Config:
        return cls(
            host=os.getenv("APP_HOST", "0.0.0.0"),
            port=_int_env("APP_PORT", 5000),
            cpu_warn=_float_env("CPU_WARN_PERCENT", 80.0),
            mem_warn=_float_env("MEM_WARN_PERCENT", 80.0),
            disk_warn=_float_env("DISK_WARN_PERCENT", 85.0),
            sample_interval=_float_env("SAMPLE_INTERVAL_SECONDS", 5.0),
            disk_path=os.getenv("DISK_PATH", "/"),
        )

    def thresholds(self) -> dict[str, float]:
        return {"cpu": self.cpu_warn, "memory": self.mem_warn, "disk": self.disk_warn}


config = Config.from_env()
