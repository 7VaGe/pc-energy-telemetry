import pynvml
from prometheus_client import Gauge

gpu_power_estimated = Gauge('gpu_power_watts_estimated', 'Potenza GPU stimata in Watt (utilizzo% * TDP)')
gpu_power_limit     = Gauge('gpu_power_limit_watts',     'TDP massimo GPU in Watt')
gpu_utilization     = Gauge('gpu_utilization_percent',   'Utilizzo GPU in percentuale')
gpu_memory_used     = Gauge('gpu_memory_used_mb',        'VRAM utilizzata in MB')
gpu_memory_total    = Gauge('gpu_memory_total_mb',       'VRAM totale in MB')
gpu_temperature     = Gauge('gpu_temperature_c',         'Temperatura GPU in gradi Celsius')
gpu_clock_core      = Gauge('gpu_clock_core_mhz',        'Frequenza core GPU in MHz')

_handle    = None
_tdp_watts = 0.0

def init():
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

    estimated_power = _tdp_watts * (utilization.gpu / 100.0)

    gpu_power_estimated.set(estimated_power)
    gpu_power_limit.set(_tdp_watts)
    gpu_utilization.set(utilization.gpu)
    gpu_memory_used.set(memory.used   / 1024 / 1024)
    gpu_memory_total.set(memory.total / 1024 / 1024)
    gpu_temperature.set(temperature)
    gpu_clock_core.set(clock)

def shutdown():
    pynvml.nvmlShutdown()