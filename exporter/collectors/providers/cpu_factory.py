# collectors/providers/cpu_factory.py
# Probes CPU power providers and returns the best available one.
#
# Priority order:
#   90  RAPLCPUProvider        -- Linux RAPL energy counter (Intel + AMD Zen 2+)
#   10  TDPEstimateCPUProvider -- universal fallback

from __future__ import annotations
import logging

from .cpu_rapl import RAPLCPUProvider
from .cpu_tdp  import TDPEstimateCPUProvider
from .base     import CPUPowerProvider

log = logging.getLogger(__name__)

_CANDIDATES: list[type[CPUPowerProvider]] = [
    RAPLCPUProvider,
    TDPEstimateCPUProvider,
]


def build() -> CPUPowerProvider:
    """
    Probe all CPU providers in priority order and return the first available one.
    TDPEstimateCPUProvider is the guaranteed fallback.
    """
    for candidate in sorted(_CANDIDATES, key=lambda c: -c.PRIORITY):
        try:
            if candidate.probe():
                provider = candidate()
                log.info(
                    f"CPU power provider selected: {candidate.__name__} "
                    f"(method={candidate.METHOD_LABEL})"
                )
                return provider
        except Exception as exc:
            log.debug(f"CPU provider {candidate.__name__} probe failed: {exc}")

    log.warning("No CPU power provider available. Using TDP estimate.")
    return TDPEstimateCPUProvider()
