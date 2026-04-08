import psutil
from prometheus_client import Gauge

cpu_utilization      = Gauge('cpu_utilization_percent',  'Utilizzo CPU in percentuale')
cpu_utilization_core = Gauge('cpu_utilization_core',     'Utilizzo per core in percentuale', ['core'])
cpu_power_estimated  = Gauge('cpu_power_watts_estimated','Potenza CPU stimata in Watt (utilizzo% * TDP)')
cpu_tdp              = Gauge('cpu_tdp_watts',            'TDP massimo CPU in Watt')
cpu_freq_current     = Gauge('cpu_freq_current_mhz',     'Frequenza CPU attuale in MHz')
cpu_freq_max         = Gauge('cpu_freq_max_mhz',         'Frequenza CPU massima in MHz')

CPU_TDP_WATTS = 120.0  # AMD Ryzen 7 7800X3D

def collect():
    utilization      = psutil.cpu_percent(interval=None)
    per_core         = psutil.cpu_percent(interval=None, percpu=True)
    freq             = psutil.cpu_freq()
    estimated_power  = CPU_TDP_WATTS * (utilization / 100.0)

    cpu_utilization.set(utilization)
    cpu_power_estimated.set(estimated_power)
    cpu_tdp.set(CPU_TDP_WATTS)

    if freq:
        cpu_freq_current.set(freq.current)
        cpu_freq_max.set(freq.max)

    for i, core_pct in enumerate(per_core):
        cpu_utilization_core.labels(core=str(i)).set(core_pct)