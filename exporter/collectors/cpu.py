# collectors/cpu.py
# CPU telemetry collector -- Prometheus publishing layer.
#
# Power measurement is delegated to a CPUPowerProvider selected at
# startup by cpu_factory.build() (priority order):
#
#    90  RAPLCPUProvider        -- Linux /sys/class/powercap energy counters
#                                  (Intel + AMD Zen 2+, ~5% accuracy)
#    10  TDPEstimateCPUProvider -- TDP * cpu_percent(), universal fallback
#                                  (~10-20% accuracy; always selected on Windows)
#
# psutil is still used directly for utilization, frequency, and per-core
# metrics since those are OS-agnostic and do not require a provider.

import psutil
import logging
from prometheus_client import Gauge
from .providers import cpu_factory
from .providers.base import CPUPowerProvider

log = logging.getLogger(__name__)

cpu_utilization      = Gauge('cpu_utilization_percent',   'Overall CPU utilization in percent')
cpu_utilization_core = Gauge('cpu_utilization_core',      'Per-core CPU utilization in percent', ['core'])
cpu_power_estimated  = Gauge('cpu_power_watts_estimated', 'CPU power draw in Watts (measured or estimated, best available)')
cpu_tdp              = Gauge('cpu_tdp_watts',             'CPU TDP ceiling in Watts')
cpu_freq_current     = Gauge('cpu_freq_current_mhz',      'Current CPU clock frequency in MHz')
cpu_freq_max         = Gauge('cpu_freq_max_mhz',          'Maximum CPU clock frequency in MHz')

_provider: CPUPowerProvider | None = None

# In-memory state exposed directly by get_power_w()
_power_w = 0.0


def init() -> None:
    """Select and initialize the best available CPU power provider."""
    global _provider
    _provider = cpu_factory.build()
    if _provider.tdp_watts > 0:
        cpu_tdp.set(_provider.tdp_watts)
    log.info(
        f"CPU collector initialized: method={_provider.METHOD_LABEL}, "
        f"TDP={_provider.tdp_watts:.0f}W"
    )


def collect():
    """Collect one CPU telemetry cycle and update all Prometheus gauges."""
    global _power_w

    utilization = psutil.cpu_percent(interval=None)
    per_core    = psutil.cpu_percent(interval=None, percpu=True)
    freq        = psutil.cpu_freq()

    power_w = _provider.get_power_w() if _provider is not None else 0.0

    cpu_utilization.set(utilization)
    cpu_power_estimated.set(power_w)

    # Update in-memory state for get_power_w()
    _power_w = power_w

    if freq:
        cpu_freq_current.set(freq.current)
        cpu_freq_max.set(freq.max)

    for i, core_pct in enumerate(per_core):
        cpu_utilization_core.labels(core=str(i)).set(core_pct)


def get_power_w() -> float:
    """Return last CPU power for energy.py (no REGISTRY scan)."""
    return _power_w
