# collectors/gpu.py
# GPU telemetry collector using the official NVIDIA Management Library (NVML)
# via the nvidia-ml-py binding.
#
# Power measurement strategy (probed at init, in priority order):
#   1. nvmlDeviceGetTotalEnergyConsumption — cumulative mJ counter, supported on
#      RTX 5080 (Blackwell). Average power = delta_mJ / delta_s / 1000.
#      Verified available on this system; used as primary measurement method.
#   2. TDP * (gpu_utilization / 100) — linear fallback when the energy counter
#      is not supported. Consistent with methodology used in PowerAPI and
#      Scaphandre when direct sensor access is unavailable.
#
# The active method is exposed via gpu_power_measurement_method (0=estimate, 1=counter).
# Both values are always published for dashboard comparison and thesis validation.

import time
import pynvml
from prometheus_client import Gauge

# Best available power — used by energy.py via get_power_w()
gpu_power_watts              = Gauge('gpu_power_watts',                  'GPU power draw in Watts (measured or estimated, best available)')

# Per-method metrics for dashboard comparison
gpu_power_measured           = Gauge('gpu_power_watts_measured',         'GPU power from energy counter (W); 0 if not supported')
gpu_power_estimated          = Gauge('gpu_power_watts_estimated',        'GPU power from TDP*utilization linear model (W)')
gpu_power_measurement_method = Gauge('gpu_power_measurement_method',     'Active power measurement method: 1=energy counter, 0=TDP estimate')

gpu_power_limit              = Gauge('gpu_power_limit_watts',            'GPU TDP ceiling in Watts')
gpu_utilization              = Gauge('gpu_utilization_percent',          'GPU core utilization in percent')
gpu_memory_used              = Gauge('gpu_memory_used_mb',               'VRAM in use (MB)')
gpu_memory_total             = Gauge('gpu_memory_total_mb',              'Total VRAM available (MB)')
gpu_temperature              = Gauge('gpu_temperature_c',                'GPU die temperature in Celsius')
gpu_clock_core               = Gauge('gpu_clock_core_mhz',               'GPU core clock frequency in MHz')

_handle                      = None
_tdp_watts                   = 0.0
_energy_counter_supported    = False
_prev_energy_mj              = None
_prev_collect_time           = None


def init() -> b