# collectors/providers/cpu_rapl.py
# CPU power measurement via Linux RAPL (Running Average Power Limit).
#
# RAPL exposes cumulative energy counters in /sys/class/powercap/intel-rapl/
# (Intel) and /sys/class/powercap/amd_energy/ (AMD Zen 2+).
#
# Power = ΔuJ / Δs / 1e6
# Accuracy: ~2-5% vs wall meter (best available on Linux without kernel driver).
#
# Requires: Linux, read permission on /sys/class/powercap/
# On most distros: readable by root only. User can add udev rule or run as root.

from __future__ import annotations
import os
import time
from .base import CPUPowerProvider

# RAPL domain paths to probe in order of preference
_RAPL_CANDIDATES = [
    # Intel RAPL — package-level (includes all cores)
    "/sys/class/powercap/intel-rapl/intel-rapl:0/energy_uj",
    # AMD energy driver (Zen 2+)
    "/sys/class/powercap/amd_energy/amd_energy:0/energy_uj",
    # Fallback: first powercap domain found
]


def _find_rapl_path() -> str | None:
    for path in _RAPL_CANDIDATES:
        if os.path.isfile(path) and os.access(path, os.R_OK):
            return path
    # Generic scan
    base = "/sys/class/powercap"
    if os.path.isdir(base):
        for entry in sorted(os.listdir(base)):
            candidate = os.path.join(base, entry, "energy_uj")
            if os.path.isfile(candidate) and os.access(candidate, os.R_OK):
                return candidate
    return None


def _read_uj(path: str) -> int:
    with open(path) as f:
        return int(f.read().strip())


class RAPLCPUProvider(CPUPowerProvider):
    """
    CPU power via Linux RAPL energy counter.
    Most accurate software-accessible method on Linux without kernel drivers.
    """

    PRIORITY    = 90
    METHOD_LABEL = "rapl_energy_counter"

    def __init__(self) -> None:
        self._path          = _find_rapl_path()
        self._prev_uj       = None
        self._prev_time     = None
        self._last_power_w  = 0.0

    @classmethod
    def probe(cls) -> bool:
        return _find_rapl_path() is not None

    def get_power_w(self) -> float:
        if self._path is None:
            return 0.0

        now_s  = time.perf_counter()
        now_uj = _read_uj(self._path)

        if self._prev_uj is not None and self._prev_time is not None:
            delta_uj = now_uj - self._prev_uj
            delta_s  = now_s  - self._prev_time
            # Handle counter wraparound (32-bit on some kernels)
            if delta_uj < 0:
                try:
                    max_path = self._path.replace("energy_uj", "max_energy_range_uj")
                    max_uj   = _read_uj(max_path)
                    delta_uj += max_uj
                except Exception:
                    delta_uj = 0
            if delta_s > 0 and delta_uj >= 0:
                self._last_power_w = (delta_uj / 1e6) / delta_s

        self._prev_uj   = now_uj
        self._prev_time = now_s
        return self._last_power_w
