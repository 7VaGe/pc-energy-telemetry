# collectors/cpu.py
# CPU telemetry collector using psutil.
#
# Intel RAPL (Running Average Power Limit) is not accessible on Windows
# without kernel-level drivers. Power draw is therefore estimated as:
# estimated_watts = TDP * (cpu_utilization / 100)
# TDP source: AMD official spec sheet for Ryzen 7 7800X3D = 120W.

import psutil
from prometheus_client import Gauge

cpu_utilization      = Gauge('cpu_utilization_percent',   'Overall CPU utilization in percent')
cpu_utilization_core = Gauge('cpu_utilization_core',      'Per-core CPU utilization in percent', ['core'])
cpu_power_estimated  = Gauge('cpu_power_watts_estimated', 'Estimated CPU power draw in Watts (TDP * utilization)')
cpu_tdp              = Gauge('cpu_tdp_watts',             'CPU TDP ceiling in Watts')
cpu_freq_current     = Gauge('cpu_freq_current_mhz',      'Current CPU clock frequency in MHz')
cpu_freq_max         = Gauge('cpu_freq_max_mhz',          'Maximum CPU clock frequency in MHz')

# AMD Ryzen 7 7800X3D rated TDP
CPU_TDP_WATTS = 120.0

def collect():
    utilization     = psutil.cpu_percent(interval=None)
    per_core        = psutil.cpu_percent(interval=None, percpu=True)
    freq            = psutil.cpu_freq()
    estimated_power = CPU_TDP_WATTS * (utilization / 100.0)

    cpu_utilization.set(utilization)
    cpu_power_estimated.set(estimated_power)
    cpu_tdp.set(CPU_TDP_WATTS)

    if freq:
        cpu_freq_current.set(freq.current)
        cpu_freq_max.set(freq.max)

    # Expose individual core utilization with a 'core' label
    for i, core_pct in enumerate(per_core):
        cpu_utilization_core.labels(core=str(i)).set(core_pct)