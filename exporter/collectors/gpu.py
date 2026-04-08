# collectors/gpu.py
# GPU telemetry collector using the official NVIDIA Management Library (NVML)
# via the nvidia-ml-py binding.
#
# Note: nvmlDeviceGetPowerUsage is not supported on the RTX 5080 (Blackwell).
# Power draw is estimated as: estimated_watts = TDP * (gpu_utilization / 100)
# This linear approximation is consistent with methodology used in PowerAPI
# and Scaphandre when direct sensor access is unavailable.

import pynvml
from prometheus_client import Gauge

gpu_power_estimated = Gauge('gpu_power_watts_estimated', 'Estimated GPU power draw in Watts (TDP * utilization)')
gpu_power_limit     = Gauge('gpu_power_limit_watts',     'GPU TDP ceiling in Watts')
gpu_utilization     = Gauge('gpu_utilization_percent',   'GPU core utilization in percent')
gpu_memory_used     = Gauge('gpu_memory_used_mb',        'VRAM in use (MB)')
gpu_memory_total    = Gauge('gpu_memory_total_mb',       'Total VRAM available (MB)')
gpu_temperature     = Gauge('gpu_temperature_c',         'GPU die temperature in Celsius')
gpu_clock_core      = Gauge('gpu_clock_core_mhz',        'GPU core clock frequency in MHz')

_handle    = None
_tdp_watts = 0.0

def init():
    # Initialize NVML and acquire handle for GPU at index 0.
    # TDP is read once at startup via nvmlDeviceGetPowerManagementLimit.
    global _handle, _tdp_watts
    pynvml.nvmlInit()
    _handle    = pynvml.nvmlDeviceGetHandleByIndex(0)
    _tdp_watts = pynvml.nvmlDeviceGetPowerManagementLimit(_handle) / 1000.0

def collect():
    if _handle is None:
        return

    utilization = pynvml.nvmlDeviceGetUtilizationRates(_handle)
    memory      = pynvml.nvmlDeviceGetMemoryInfo(_handle)
    temperature = pynvml.nvmlDeviceGetTemperature(_handle, pynvml.NVML_TEMPERATURE_GPU)
    clock       = pynvml.nvmlDeviceGetClockInfo(_handle, pynvml.NVML_CLOCK_GRAPHICS)

    # Linear power estimation — see module docstring for methodology note
    estimated_power = _tdp_watts * (utilization.gpu / 100.0)

    gpu_power_estimated.set(estimated_power)
    gpu_power_limit.set(_tdp_watts)
    gpu_utilization.set(utilization.gpu)
    gpu_memory_used.set(memory.used   / 1024 / 1024)
    gpu_memory_total.set(memory.total / 1024 / 1024)
    gpu_temperature.set(temperature)
    gpu_clock_core.set(clock)

def shutdown():
    # Release NVML resources on clean exit
    pynvml.nvmlShutdown()