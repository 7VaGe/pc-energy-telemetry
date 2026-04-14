# collectors/providers/gpu_amd.py
# AMD GPU power provider via ROCm SMI.
#
# Requirements: Linux, ROCm installed, `rocm-smi` CLI in PATH.
# Tested on: RX 6000 / RX 7000 series (RDNA 2/3).
#
# Reads GPU power via:
#   rocm-smi --showpower --json
# which returns {"card0": {"Current Socket Graphics Package Power (W)": "120.0"}}
#
# If rocm-smi is not available, probe() returns False and the factory
# falls through to the TDP estimate provider.

from __future__ import annotations
import json
import shutil
import subprocess
import psutil
from .base import GPUPowerProvider, GPUSample


class AMDROCmProvider(GPUPowerProvider):
    """
    GPU power for AMD cards via rocm-smi CLI.
    Available only on Linux with ROCm stack installed.
    """

    PRIORITY    = 80
    METHOD_LABEL = "rocm_smi"

    @classmethod
    def probe(cls) -> bool:
        # rocm-smi must be in PATH and return exit code 0
        if shutil.which("rocm-smi") is None:
            return False
        try:
            result = subprocess.run(
                ["rocm-smi", "--showpower", "--json"],
                capture_output=True, text=True, timeout=3
            )
            return result.returncode == 0
        except Exception:
            return False

    def collect(self) -> GPUSample:
        power_w       = self._read_power_w()
        utilization   = self._read_utilization()
        memory_used   = self._read_memory_mb()

        self._best_w          = power_w
        self._utilization_pct = utilization

        return GPUSample(
            power_w         = power_w,
            utilization_pct = utilization,
            memory_used_mb  = memory_used,
            measured_valid  = power_w > 0,
        )

    def get_power_w(self) -> float:
        return self._best_w

    def get_utilization(self) -> float:
        return self._utilization_pct

    def __init__(self) -> None:
        self._best_w          = 0.0
        self._utilization_pct = 0.0

    def _read_power_w(self) -> float:
        try:
            result = subprocess.run(
                ["rocm-smi", "--showpower", "--json"],
                capture_output=True, text=True, timeout=3
            )
            data = json.loads(result.stdout)
            for card_data in data.values():
                for key, val in card_data.items():
                    if "Power" in key and "W" in key:
                        return float(val)
        except Exception:
            pass
        return 0.0

    def _read_utilization(self) -> float:
        try:
            result = subprocess.run(
                ["rocm-smi", "--showuse", "--json"],
                capture_output=True, text=True, timeout=3
            )
            data = json.loads(result.stdout)
            for card_data in data.values():
                for key, val in card_data.items():
                    if "GPU use" in key or "GFX Activity" in key:
                        return float(str(val).strip("%"))
        except Exception:
            pass
        return 0.0

    def _read_memory_mb(self) -> float:
        try:
            result = subprocess.run(
                ["rocm-smi", "--showmemuse", "--json"],
                capture_output=True, text=True, timeout=3
            )
            data = json.loads(result.stdout)
            for card_data in data.values():
                for key, val in card_data.items():
                    if "VRAM" in key and "Used" in key:
                        return float(val) / 1024.0  # KB -> MB
        except Exception:
            pass
        return 0.0
