# collectors/gpu.py
# GPU telemetry collector -- Prometheus publishing layer.
#
# Hardware access is fully delegated to a GPUPowerProvider selected at
# startup by gpu_factory.build() (priority order):
#
#   100  NvidiaEnergyCounterProvider  -- NVML mJ counter, RTX 30xx/40xx/50xx
#    90  NvidiaPowerUsageProvider     -- NVML sensor, Pascal/Turing/Ampere
#    80  AMDROCmProvider              -- rocm-smi CLI, Linux AMD
#    10  TDPEstimateGPUProvider       -- TDP * util%, universal fallback
#
# This module only manages Prometheus gauges and exposes the in-memory
# state getters used by energy.py and the classifier.
#
# Two power metrics are always published for thesis validation:
#   gpu_power_watts_measured  -- non-zero only when a direct reading is valid
#   gpu_power_watts_estimated -- TDP * utilization (linear model, always computed)
#   gpu_power_watts           -- best available: measured if valid, else estimated

import logging
from prometheus_client import Gauge
from .providers import gpu_factory
from .providers.base import GPUPowerProvider

log = logging.getLogger(__name__)

# Best available power -- used by energy.py via get_power_w()
gpu_power_watts              = Gauge('gpu_power_watts',               'GPU power draw in Watts (measured or estimated, best available)')

# Per-method metrics for dashboard comparison and thesis validation
gpu_power_measured           = Gauge('gpu_power_watts_measured',      'GPU power from direct sensor (W); 0 if not supported or first cycle')
gpu_power_estimated          = Gauge('gpu_power_watts_estimated',      'GPU power from TDP*utilization linear model (W)')
gpu_power_measurement_method = Gauge('gpu_power_measurement_method',  'Active power method: 1=direct measurement, 0=TDP estimate')

gpu_power_limit              = Gauge('gpu_power_limit_watts',         'GPU TDP ceiling in Watts')
gpu_utilization              = Gauge('gpu_utilization_percent',       'GPU core utilization in percent')
gpu_memory_used              = Gauge('gpu_memory_used_mb',            'VRAM in use (MB)')
gpu_memory_total             = Gauge('gpu_memory_total_mb',           'Total VRAM available (MB)')
gpu_temperature              = Gauge('gpu_temperature_c',             'GPU die temperature in Celsius')
gpu_clock_core               = Gauge('gpu_clock_core_mhz',            'GPU core clock frequency in MHz')

_provider: GPUPowerProvider | None = None

# In-memory state exposed directly by get_power_w() and get_utilization()
# -- avoids REGISTRY.collect() reads in the hot path.
_best_w      = 0.0
_utilization = 0.0


def init() -> bool:
    """
    Select and initialize the best available GPU power provider.
    Returns True if a direct-measurement method is active (not TDP estimate).
    """
    global _provider
    _provider    = gpu_factory.build()
    is_measured  = _provider.METHOD_LABEL != "tdp_estimate"
    gpu_power_limit.set(_provider.tdp_watts)
    gpu_power_measurement_method.set(1 if is_measured else 0)
    log.info(
        f"GPU collector initialized: method={_provider.METHOD_LABEL}, "
        f"TDP={_provider.tdp_watts:.0f}W, measured={is_measured}"
    )
    return is_measured


def collect():
    """Collect one GPU telemetry cycle and update all Prometheus gauges."""
    global _best_w, _utilization

    if _provider is None:
        return

    sample         = _provider.collect()
    tdp_estimate_w = _provider.tdp_watts * (sample.utilization_pct / 100.0)

    # gpu_power_watts_measured: non-zero only when a valid direct reading exists.
    # gpu_power_watts: best available -- measured when valid, else TDP estimate.
    measured_w = sample.power_w if sample.measured_valid else 0.0
    best_w     = sample.power_w if sample.measured_valid else tdp_estimate_w

    _best_w      = best_w
    _utilization = sample.utilization_pct

    gpu_power_watts.set(best_w)
    gpu_power_measured.set(measured_w)
    gpu_power_estimated.set(tdp_estimate_w)
    gpu_utilization.set(sample.utilization_pct)
    gpu_memory_used.set(sample.memory_used_mb)
    gpu_memory_total.set(sample.memory_total_mb)
    gpu_temperature.set(sample.temperature_c)
    gpu_clock_core.set(sample.clock_mhz)


def get_power_w() -> float:
    """Return best available GPU power for energy.py (no REGISTRY scan)."""
    return _best_w


def get_utilization() -> float:
    """Return last GPU utilization percent for the classifier (no REGISTRY scan)."""
    return _utilization


def shutdown():
    """Release GPU handles via the active provider."""
    if _provider is not None:
        _provider.shutdown()
