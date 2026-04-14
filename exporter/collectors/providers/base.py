# collectors/providers/base.py
# Abstract base classes for hardware power measurement providers.
#
# Design: Chain of Responsibility with runtime probing.
# Each provider implements probe() to declare availability and
# measure_w() / estimate_w() for actual measurement.
#
# Factories select the best available provider at startup,
# so the rest of the codebase is fully vendor-agnostic.

from __future__ import annotations
from abc import ABC, abstractmethod


class GPUPowerProvider(ABC):
    """Abstract interface for GPU power measurement."""

    # Higher = preferred when multiple providers are available.
    PRIORITY: int = 0

    # Human-readable label published to Prometheus for observability.
    METHOD_LABEL: str = "unknown"

    @classmethod
    @abstractmethod
    def probe(cls) -> bool:
        """Return True if this provider is available on this system."""

    @abstractmethod
    def collect(self) -> GPUSample:
        """
        Collect one sample from the GPU.
        Returns a GPUSample with power, utilization, memory, temp, clock.
        """

    @property
    def tdp_watts(self) -> float:
        """Return GPU TDP in Watts (used by gpu.py for the linear estimate metric)."""
        return getattr(self, '_tdp_watts', 0.0)

    def get_power_w(self) -> float:
        """Return best available power in Watts (direct or estimated)."""
        return 0.0

    def get_utilization(self) -> float:
        """Return GPU utilization percent [0-100]."""
        return 0.0

    def shutdown(self) -> None:
        """Release any open handles."""


class CPUPowerProvider(ABC):
    """Abstract interface for CPU power measurement."""

    PRIORITY: int = 0
    METHOD_LABEL: str = "unknown"

    @property
    def tdp_watts(self) -> float:
        """Return CPU TDP in Watts (published to cpu_tdp_watts gauge)."""
        return getattr(self, '_tdp_watts', 0.0)

    @classmethod
    @abstractmethod
    def probe(cls) -> bool:
        """Return True if this provider is available on this system."""

    @abstractmethod
    def get_power_w(self) -> float:
        """Return estimated or measured CPU power in Watts."""


class GPUSample:
    """Value object for one GPU telemetry sample."""

    __slots__ = (
        "power_w", "utilization_pct", "memory_used_mb",
        "memory_total_mb", "temperature_c", "clock_mhz",
        "measured_valid",
    )

    def __init__(
        self,
        power_w: float = 0.0,
        utilization_pct: float = 0.0,
        memory_used_mb: float = 0.0,
        memory_total_mb: float = 0.0,
        temperature_c: float = 0.0,
        clock_mhz: float = 0.0,
        measured_valid: bool = False,
    ) -> None:
        self.power_w         = power_w
        self.utilization_pct = utilization_pct
        self.memory_used_mb  = memory_used_mb
        self.memory_total_mb = memory_total_mb
        self.temperature_c   = temperature_c
        self.clock_mhz       = clock_mhz
        self.measured_valid  = measured_valid
