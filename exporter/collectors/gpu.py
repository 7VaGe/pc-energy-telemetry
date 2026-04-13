# collectors/gpu.py
# GPU telemetry collector using the official NVIDIA Management Library (NVML)
# via the nvidia-ml-py binding.
#
# Power measurement strategy (probed at init, in priority order):
#   1. nvmlDeviceGetTotalEnergyConsumption -- cumulative mJ counter, supported on
#      RTX 5080 (Blackwell). Average power = delta_mJ / delta_s / 1000.
#      Verified available on this system; used as primary measurement method.
#   2. TDP * (gpu_utilization / 100) -- linear fallback when the energy counter
#      is not supported. Consistent with methodology used in PowerAPI and
#      Scaphandre when direct sensor access is unavailable.
#
# The active method is exposed via gpu_power_measurement_method (0=estimate, 1=counter).
# Both values are always published for dashboard comparison and thesis validation.

import time
import pynvml
from prometheus_client import Gauge

# Best available power -- used by energy.py via get_power_w()
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

# In-memory state exposed directly by get_power_w() and get_utilization()
# -- avoids REGISTRY.collect() reads in the hot path.
_best_w        = 0.0   # best available GPU power (measured or estimated)
_utilization   = 0.0   # last GPU utilisation percent


def init() -> bool:
    # Initialize NVML, acquire GPU handle, probe energy counter availability.
    # Returns True if the energy counter is supported on this GPU.
    global _handle, _tdp_watts, _energy_counter_supported

    pynvml.nvmlInit()
    _handle    = pynvml.nvmlDeviceGetHandleByIndex(0)
    _tdp_watts = pynvml.nvmlDeviceGetPowerManagementLimit(_handle) / 1000.0

    try:
        pynvml.nvmlDeviceGetTotalEnergyConsumption(_handle)
        _energy_counter_supported = True
    except pynvml.NVMLError:
        _energy_counter_supported = False

    gpu_power_limit.set(_tdp_watts)
    gpu_power_measurement_method.set(1 if _energy_counter_supported else 0)

    return _energy_counter_supported


def collect():
    global _prev_energy_mj, _prev_collect_time, _best_w, _utilization

    if _handle is None:
        return

    utilization = pynvml.nvmlDeviceGetUtilizationRates(_handle)
    memory      = pynvml.nvmlDeviceGetMemoryInfo(_handle)
    temperature = pynvml.nvmlDeviceGetTemperature(_handle, pynvml.NVML_TEMPERATURE_GPU)
    clock       = pynvml.nvmlDeviceGetClockInfo(_handle, pynvml.NVML_CLOCK_GRAPHICS)

    # --- TDP linear estimate (always computed for comparison) ---
    tdp_estimate_w = _tdp_watts * (utilization.gpu / 100.0)
    gpu_power_estimated.set(tdp_estimate_w)

    # --- Energy counter measurement ---
    measured_w     = 0.0
    measured_valid = False
    if _energy_counter_supported:
        now_s     = time.perf_counter()
        energy_mj = pynvml.nvmlDeviceGetTotalEnergyConsumption(_handle)

        if _prev_energy_mj is not None and _prev_collect_time is not None:
            delta_mj = energy_mj - _prev_energy_mj
            delta_s  = now_s    - _prev_collect_time
            if delta_s > 0 and delta_mj >= 0:
                measured_w     = (delta_mj / 1000.0) / delta_s  # mJ -> J -> W
                measured_valid = True

        _prev_energy_mj    = energy_mj
        _prev_collect_time = now_s

    gpu_power_measured.set(measured_w)

    # --- Publish best available value ---
    # Fall back to TDP estimate until the first valid delta is computed (first cycle).
    best_w = measured_w if measured_valid else tdp_estimate_w
    gpu_power_watts.set(best_w)

    # Update in-memory state for get_power_w() / get_utilization()
    _best_w      = best_w
    _utilization = float(utilization.gpu)

    gpu_utilization.set(utilization.gpu)
    gpu_memory_used.set(memory.used   / 1024 / 1024)
    gpu_memory_total.set(memory.total / 1024 / 1024)
    gpu_temperature.set(temperature)
    gpu_clock_core.set(clock)


def get_power_w() -> float:
    # Returns the best available GPU power for energy.py.
    # Reads from in-memory state set by collect() -- no REGISTRY scan.
    return _best_w


def get_utilization() -> float:
    # Returns the last GPU utilization percent for the classifier.
    # Reads from in-memory state set by collect() -- no REGISTRY scan.
    return _utilization


def shutdown():
    pynvml.nvmlShutdown()
