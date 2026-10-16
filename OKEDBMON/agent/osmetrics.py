"""Host CPU and memory sampled on the database server."""

from __future__ import annotations

from pathlib import Path

_PREVIOUS: tuple[int, int] | None = None


def read_host_metrics(proc_root: Path | None = None) -> dict[str, float | None]:
    root = proc_root or Path("/proc")
    cpu = _cpu_percent(root / "stat")
    mem = _mem_percent(root / "meminfo")
    return {"cpu_usage": cpu, "mem_usage": mem}


def _cpu_percent(stat_path: Path) -> float | None:
    global _PREVIOUS
    if not stat_path.exists():
        return None
    line = ""
    for raw in stat_path.read_text(encoding="utf-8").splitlines():
        if raw.startswith("cpu "):
            line = raw
            break
    if not line:
        return None
    parts = [int(part) for part in line.split()[1:]]
    idle = parts[3] + (parts[4] if len(parts) > 4 else 0)
    total = sum(parts)
    previous = _PREVIOUS
    _PREVIOUS = (total, idle)
    if previous is None:
        return None
    total_delta = total - previous[0]
    idle_delta = idle - previous[1]
    if total_delta <= 0:
        return None
    return round((total_delta - idle_delta) * 100 / total_delta, 2)


def _mem_percent(meminfo: Path) -> float | None:
    if not meminfo.exists():
        return None
    values: dict[str, int] = {}
    for raw in meminfo.read_text(encoding="utf-8").splitlines():
        key, _, rest = raw.partition(":")
        number = rest.strip().split()[0]
        if number.isdigit():
            values[key] = int(number)
    total = values.get("MemTotal")
    if not total:
        return None
    available = values.get("MemAvailable", values.get("MemFree", 0))
    return round((total - available) * 100 / total, 2)
