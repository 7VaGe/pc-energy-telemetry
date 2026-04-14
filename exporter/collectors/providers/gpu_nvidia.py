# collectors/providers/gpu_nvidia.py
# NVIDIA GPU power providers via NVML (nvidia-ml-py).
#
# Two providers in priority order:
#   1. NvidiaEnergyCounterProvider  -- cumulative mJ counter, RTX 30xx+ / Blackwell
#      power = ΔmJ / Δt / 1000  (most accurate, ~1-3% vs wall meter)
#   2. NvidiaPowerUsageProvider     -- instantaneous sensor, Pascal / Turing / Ampere
#      power = nvmlDeviceGetPowerUsage() / 1000  (accurate, NOT supported on Blackwell)
#
# Both fall back to TDP * utilization on the first cycle or when unavailable.

from __future__ import annotations
import time
from .base import GPUPowerProvider, GPUSample

try:
    import pynvml as _pynvml
    _PYNVML_AVAILABLE = True
except ImportError:
    _PYNVML_AVAILABLE = False


class _NvidiaBase(GPUPowerProvider):
    """Shared NVML initialisation logic for all NVIDIA providers."""

    def __init__(self) -> None:
        self._handle          = None
        self._tdp_watts       = 0.0
        self._best_w          = 0.0
        self._utilization_pct = 0.0

    def _init_handle(self) -> None:
        _pynvml.nvmlInit()
        self._handle    = _pynvml.nvmlDeviceGetHandleByIndex(0)
        self._tdp_watts = _pynvml.nvmlDeviceGetPowerManagementLimit(self._handle) / 1000.0

    def _base_sample(self) -> tuple:
        """Return (utilization, memory, temperature, clock) from NVML."""
        util  = _pynvml.nvmlDeviceGetUtilizationRates(self._handle)
        mem   = _pynvml.nvmlDeviceGetMemoryInfo(self._handle)
        temp  = _pynvml.nvmlDeviceGetTemperature(self._handle, _pynvml.NVML_TEMPERATURE_GPU)
        clock = _pynvml.nvmlDeviceGetClockInfo(self._handle, _pynvml.NVML_CLOCK_GRAPHICS)
        return util, mem, temp, clock

    def get_power_w(self) -> float:
        return self._best_w

    def get_utilization(self) -> float:
        return self._utilization_pct

    def shutdown(self) -> None:
        try:
            _pynvml.nvmlShutdown()
        except Exception:
            pass


class NvidiaEnergyCounterProvider(_NvidiaBase):
    """
    GPU power via cumulative mJ energy counter.
    Supported on RTX 30xx, RTX 40xx, RTX 50xx (Blackwell).
    NOT supported on Pascal (GTX 10xx) and Turing (RTX 20xx) on some systems.
    """

    PRIORITY    = 100
    METHOD_LABEL = "nvml_energy_counter"

    def __init__(self) -> None:
        super().__init__()
        self._prev_energy_mj   = None
        self._prev_collect_time = None
        self._measured_valid   = False
        self._init_handle()

    @classmethod
    def probe(cls) -> bool:
        if not _PYNVML_AVAILABLE:
            return False
        try:
            _pynvml.nvmlInit()
            h = _pynvml.nvmlDeviceGetHandleByIndex(0)
            _pynvml.nvmlDeviceGetTotalEnergyConsumption(h)
            return True
        except Exception:
            return False

    def collect(self) -> GPUSample:
        util, mem, temp, clock = self._base_sample()

        tdp_estimate_w = self._tdp_watts * (util.gpu / 100.0)

        now_s     = time.perf_counter()
        energy_mj = _pynvml.nvmlDeviceGetTotalEnergyConsumption(self._handle)

        measured_w     = 0.0
        measured_valid = False
        if self._prev_energy_mj is not None and self._prev_collect_time is not None:
            delta_mj = energy_mj - self._prev_energy_mj
            delta_s  = now_s    - self._prev_collect_time
            if delta_s > 0 and delta_mj >= 0:
                measured_w     = (delta_mj / 1000.0) / delta_s
                measured_valid = True

        self._prev_energy_mj    = energy_mj
        self._prev_collect_time = now_s

        best_w = measured_w if measured_valid else tdp_estimate_w

        self._best_w          = best_w
        self._utilization_pct = float(util.gpu)
        self._measured_valid  = measured_valid

        return GPUSample(
            power_w         = best_w,
            utilization_pct = float(util.gpu),
            memory_used_mb  = mem.used   / 1024 / 1024,
            memory_total_mb = mem.total  / 1024 / 1024,
            temperature_c   = float(temp),
            clock_mhz       = float(clock),
            measured_valid  = measured_valid,
        )


class NvidiaPowerUsageProvider(_NvidiaBase):
    """
    GPU power via instantaneous sensor (nvmlDeviceGetPowerUsage).
    Supported on Pascal / Turing / Ampere / Ada Lovelace.
    NOT supported on RTX 5080 Blackwell (returns NVMLError).
    """

    PRIORITY    = 90
    METHOD_LABEL = "nvml_power_usage"

    def __init__(self) -> None:
        super().__init__()
        self._init_handle()

    @classmethod
    def probe(cls) -> bool:
        if not _PYNVML_AVAILABLE:
            return False
        try:
            _pynvml.nvmlInit()
            h = _pynvml.nvmlDeviceGetHandleByIndex(0)
            _pynvml.nvmlDeviceGetPowerUsage(h)
            return True
        except Exception:
            return False

    def collect(self) -> GPUSample:
        util, mem, temp, clock = self._base_sample()

        power_mw = _pynvml.nvmlDeviceGetPowerUsage(self._handle)
        power_w  = power_mw / 1000.0

        self._best_w          = power_w
        self._utilization_pct = float(util.gpu)

        return GPUSample(
            power_w         = power_w,
            utilization_pct = float(util.gpu),
            memory_used_mb  = mem.used   / 1024 / 1024,
            memory_total_mb = mem.total  / 1024 / 1024,
            temperature_c   = float(temp),
            clock_mhz       = float(clock),
            measured_valid  = True,
        )
