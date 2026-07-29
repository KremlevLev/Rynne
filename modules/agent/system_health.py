from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

import psutil


@dataclass(frozen=True, slots=True)
class ProcessPressure:
    pid: int
    name: str
    cpu_percent: float
    memory_percent: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "pid": self.pid,
            "name": self.name,
            "cpu_percent": round(self.cpu_percent, 1),
            "memory_percent": round(
                self.memory_percent,
                1,
            ),
        }


@dataclass(frozen=True, slots=True)
class SystemHealthSnapshot:
    cpu_percent: float
    memory_percent: float
    available_memory_bytes: int
    top_processes: tuple[ProcessPressure, ...]
    sampled_at: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "cpu_percent": round(self.cpu_percent, 1),
            "memory_percent": round(
                self.memory_percent,
                1,
            ),
            "available_memory_bytes": (
                self.available_memory_bytes
            ),
            "top_processes": [
                process.to_dict()
                for process in self.top_processes
            ],
            "sampled_at": self.sampled_at,
        }


class SystemHealthSampler:
    """Cheap non-blocking psutil sampler with per-process deltas."""

    def __init__(self) -> None:
        self._processes: dict[int, psutil.Process] = {}
        psutil.cpu_percent(interval=None)

    def _process_pressure(self) -> list[ProcessPressure]:
        seen: set[int] = set()
        pressure: list[ProcessPressure] = []

        for process in psutil.process_iter():
            seen.add(process.pid)
            cached = self._processes.setdefault(
                process.pid,
                process,
            )
            try:
                cpu_percent = float(
                    cached.cpu_percent(interval=None)
                )
                memory_percent = float(
                    cached.memory_percent()
                )
                name = str(cached.name() or cached.pid)
            except (
                psutil.AccessDenied,
                psutil.NoSuchProcess,
                psutil.ZombieProcess,
                OSError,
            ):
                continue

            if cpu_percent <= 0 and memory_percent <= 0:
                continue
            pressure.append(
                ProcessPressure(
                    pid=cached.pid,
                    name=name,
                    cpu_percent=max(0.0, cpu_percent),
                    memory_percent=max(
                        0.0,
                        memory_percent,
                    ),
                )
            )

        for stale_pid in set(self._processes) - seen:
            self._processes.pop(stale_pid, None)

        return sorted(
            pressure,
            key=lambda item: max(
                item.cpu_percent,
                item.memory_percent,
            ),
            reverse=True,
        )[:5]

    def sample(self) -> SystemHealthSnapshot:
        memory = psutil.virtual_memory()
        return SystemHealthSnapshot(
            cpu_percent=max(
                0.0,
                float(psutil.cpu_percent(interval=None)),
            ),
            memory_percent=max(
                0.0,
                float(memory.percent),
            ),
            available_memory_bytes=max(
                0,
                int(memory.available),
            ),
            top_processes=tuple(
                self._process_pressure()
            ),
            sampled_at=time.time(),
        )
