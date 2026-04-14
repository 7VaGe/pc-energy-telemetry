# collectors/providers/cpu_tdp.py
# Universal CPU power estimate via TDP * psutil.cpu_percent().
#
# Works on any OS. TDP resolved in priority order:
#   1. Lookup table keyed by CPU model string
#   2. Conservative default: 65W
#
# Accuracy: ~10-20%. Only fallback; RAPL should be preferred on Linux.

from __future__ import annotations
import platform
import psutil
from .base import CPUPowerProvider

# CPU TDP lookup — lowercase model string fragment -> Watts
# Sources: AMD/Intel official spec sheets, AnandTech/TechPowerUp
CPU_TDP_TABLE: dict[str, float] = {
    # AMD Ryzen 7000 (Zen 4 / AM5)
    "7950x3d": 120.0,
    "7950x":   170.0,
    "7900x3d": 120.0,
    "7900x":   170.0,
    "7900":    65.0,
    "7800x3d": 120.0,
    "7700x":   105.0,
    "7700":    65.0,
    "7600x":   105.0,
    "7600":    65.0,
    # AMD Ryzen 5000 (Zen 3 / AM4)
    "5950x":   105.0,
    "5900x":   105.0,
    "5800x3d": 105.0,
    "5800x":   105.0,
    "5700x":   65.0,
    "5600x":   65.0,
    "5600":    65.0,
    # Intel Core 13th gen (Raptor Lake)
    "13900k":  125.0,
    "13700k":  125.0,
    "13600k":  125.0,
    # Intel Core 12th gen (Alder Lake)
    "12900k":  125.0,
    "12700k":  125.0,
    "12600k":  125.0,
    # Intel Core 14th gen
    "14900k":  125.0,
    "14700k":  125.0,
    "14600k":  125.0,
    # Apple Silicon (GPU share, rough estimate for CPU portion)
    "apple m1": 15.0,
    "apple m2": 20.0,
    "apple m3": 22.0,
    "apple m4": 25.0,
    # Generic notebook
    "i7-12700h": 45.0,
    "i7-13700h": 45.0,
    "ryzen 7 6800h": 45.0,
    "ryzen 9 6900hx": 45.0,
}

_DEFAULT_TDP_W = 65.0  # conservative desktop default


def _resolve_cpu_tdp() -> tuple[float, str]:
    """Return (tdp_watts, source_label)."""
    cpu_model = platform.processor().lower()
    for fragment, tdp in CPU_TDP_TABLE.items():
        if fragment in cpu_model:
            return tdp, f"lookup({fragment})"
    return _DEFAULT_TDP_W, "default"


class TDPEstimateCPUProvider(CPUPowerProvider):
    """
    CPU power estimate: TDP * psutil.cpu_percent().
    Universal fallback guaranteed to work on any OS.
    """

    PRIORITY    = 10
    METHOD_LABEL = "tdp_estimate"

    def __init__(self) -> None:
        self._tdp_watts, self._tdp_source = _resolve_cpu_tdp()

    @classmethod
    def probe(cls) -> bool:
        return True  # always available

    def get_power_w(self) -> float:
        util_pct = psutil.cpu_percent(interval=None)
        return self._tdp_watts * (util_pct / 100.0)
