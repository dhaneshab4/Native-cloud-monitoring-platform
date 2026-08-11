"""System metric collection and Prometheus instrumentation.

Two consumers are served from one collection pass: the JSON API used by the
dashboard, and the Prometheus text endpoint used by the scraper. Both read the
same snapshot so the dashboard can never disagree with an alert.
"""

from __future__ import annotations

import platform
import time
from dataclasses import asdict, dataclass

import psutil
from prometheus_client import CollectorRegistry, Gauge, generate_latest

from app.config import config

registry = CollectorRegistry()

CPU = Gauge("system_cpu_percent", "CPU utilisation percent", registry=registry)
MEM = Gauge("system_memory_percent", "Memory utilisation percent", registry=registry)
MEM_BYTES = Gauge("system_memory_used_bytes", "Memory used in bytes", registry=registry)
DISK = Gauge("system_disk_percent", "Disk utilisation percent", ["path"], registry=registry)
LOAD = Gauge("system_load_average", "Load average", ["window"], registry=registry)
UPTIME = Gauge("system_uptime_seconds", "Host uptime in seconds", registry=registry)
STATUS = Gauge("system_status", "1 healthy, 0 degraded", registry=registry)

_STARTED = time.time()


@dataclass(frozen=True)
class Snapshot:
    cpu_percent: float
    memory_percent: float
    memory_used_bytes: int
    memory_total_bytes: int
    disk_percent: float
    disk_path: str
    load_1m: float
    load_5m: float
    load_15m: float
    uptime_seconds: float
    process_count: int
    status: str
    breaches: list[str]

    def as_dict(self) -> dict:
        return asdict(self)


def _load_average() -> tuple[float, float, float]:
    """Load average, or zeros where the platform does not expose one."""
    try:
        return psutil.getloadavg()
    except (AttributeError, OSError):
        return (0.0, 0.0, 0.0)


def collect() -> Snapshot:
    """Take one reading of every metric and decide health from the thresholds."""
    cpu = psutil.cpu_percent(interval=None)
    mem = psutil.virtual_memory()
    disk = psutil.disk_usage(config.disk_path)
    load_1, load_5, load_15 = _load_average()

    breaches = []
    if cpu >= config.cpu_warn:
        breaches.append(f"cpu {cpu:.1f}% >= {config.cpu_warn:.0f}%")
    if mem.percent >= config.mem_warn:
        breaches.append(f"memory {mem.percent:.1f}% >= {config.mem_warn:.0f}%")
    if disk.percent >= config.disk_warn:
        breaches.append(f"disk {disk.percent:.1f}% >= {config.disk_warn:.0f}%")

    return Snapshot(
        cpu_percent=round(cpu, 2),
        memory_percent=round(mem.percent, 2),
        memory_used_bytes=mem.used,
        memory_total_bytes=mem.total,
        disk_percent=round(disk.percent, 2),
        disk_path=config.disk_path,
        load_1m=round(load_1, 2),
        load_5m=round(load_5, 2),
        load_15m=round(load_15, 2),
        uptime_seconds=round(time.time() - psutil.boot_time(), 0),
        process_count=len(psutil.pids()),
        status="degraded" if breaches else "healthy",
        breaches=breaches,
    )


def publish(snapshot: Snapshot) -> None:
    """Mirror a snapshot into the Prometheus registry."""
    CPU.set(snapshot.cpu_percent)
    MEM.set(snapshot.memory_percent)
    MEM_BYTES.set(snapshot.memory_used_bytes)
    DISK.labels(path=snapshot.disk_path).set(snapshot.disk_percent)
    LOAD.labels(window="1m").set(snapshot.load_1m)
    LOAD.labels(window="5m").set(snapshot.load_5m)
    LOAD.labels(window="15m").set(snapshot.load_15m)
    UPTIME.set(snapshot.uptime_seconds)
    STATUS.set(1 if snapshot.status == "healthy" else 0)


def prometheus_payload() -> bytes:
    """Collect, publish and render the Prometheus exposition format."""
    publish(collect())
    return generate_latest(registry)


def host_info() -> dict:
    return {
        "hostname": platform.node(),
        "platform": f"{platform.system()} {platform.release()}",
        "python": platform.python_version(),
        "cpu_count": psutil.cpu_count(logical=True),
        "app_uptime_seconds": round(time.time() - _STARTED, 0),
    }
