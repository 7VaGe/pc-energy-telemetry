# collectors/providers/gpu_factory.py
# Probes available GPU power providers at startup and returns the best one.
#
# Provider priority (highest first):
#   100  NvidiaEnergyCounterProvider  -- RTX 30xx/40xx/50xx, NVML mJ counter
#    90  NvidiaPowerUsageProvider     -- Pascal/Turing/Ampere, NVML sensor
#    80  AMDROCmProvider              -- Linux AMD via rocm-smi CLI
#    10  TDPEstimateGPUProvider       -- universal fallback (always available)

from __future__ import annotations
import logging

from .gpu_nvidia  import NvidiaEnergyCounterProvider, NvidiaPowerUsageProvider
from .gpu_amd     import AMDROCmProvider
from .gpu_tdp     import TDPEstimateGPUProvider
from .base        import GPUPowerProvider

log = logging.getLogger(__name__)

_CANDIDATES: list[type[GPUPowerProvider]] = [
    NvidiaEnergyCounterProvider,
    NvidiaPowerUsageProvider,
    AMDROCmProvider,
    TDPEstimateGPUProvider,
]


def build() -> GPUPowerProvider:
    """
    Probe all candidates in priority order and instantiate the first available one.
    Always returns a usable provider (TDPEstimateGPUProvider is the guaranteed fallback).
    """
    for candidate in sorted(_CANDIDATES, key=lambda c: -c.PRIORITY):
        try:
            if candidate.probe():
                provider = candidate()
                log.info(
                    f"GPU power provider selected: {candidate.__name__} "
                    f"(method={candidate.METHOD_LABEL})"
                )
                return provider
        except Exception as exc:
            log.debug(f"GPU provider {candidate.__name__} probe failed: {exc}")

    # Should never reach here since TDPEstimateGPUProvider.probe() is always True
    log.warning("No GPU power provider available. Using TDP estimate.")
    return TDPEstimateGPUProvider()
