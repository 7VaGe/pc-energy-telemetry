# tests/test_gpu_collector.py
# Unit tests for collectors/gpu.py
#
# All pynvml calls are mocked -- no real GPU required.
# Prometheus Gauges are module-level singletons: tests reset only the
# private state variables instead of reloading the module, to avoid
# CollectorRegistry duplicate-registration errors.

import sys
import types
import unittest
from unittest.mock import MagicMock, patch


# ---------------------------------------------------------------------------
# Build a minimal pynvml stub so the module can be imported without a GPU.
# ---------------------------------------------------------------------------
def _make_pynvml_stub():
    stub = types.ModuleType('pynvml')

    class NVMLError(Exception):
        pass

    class NVMLError_NotSupported(NVMLError):
        pass

    stub.NVMLError              = NVMLError
    stub.NVMLError_NotSupported = NVMLError_NotSupported
    stub.nvmlInit               = MagicMock()
    stub.nvmlShutdown           = MagicMock()
    stub.nvmlDeviceGetHandleByIndex           = MagicMock(return_value='handle')
    stub.nvmlDeviceGetPowerManagementLimit    = MagicMock(return_value=360_000)
    stub.nvmlDeviceGetTotalEnergyConsumption  = MagicMock(return_value=100_000)
    stub.nvmlDeviceGetUtilizationRates        = MagicMock(return_value=MagicMock(gpu=0))
    stub.nvmlDeviceGetMemoryInfo              = MagicMock(return_value=MagicMock(used=0, total=16 * 1024**3))
    stub.nvmlDeviceGetTemperature             = MagicMock(return_value=40)
    stub.nvmlDeviceGetClockInfo               = MagicMock(return_value=2400)
    stub.NVML_TEMPERATURE_GPU                 = 0
    stub.NVML_CLOCK_GRAPHICS                  = 0
    return stub


sys.modules['pynvml'] = _make_pynvml_stub()

import collectors.gpu as gpu_module


def _reset_gpu_state():
    # Reset private state without reloading (avoids Prometheus duplicate errors).
    gpu_module._handle                   = None
    gpu_module._tdp_watts                = 0.0
    gpu_module._energy_counter_supported = False
    gpu_module._prev_energy_mj           = None
    gpu_module._prev_collect_time        = None
    gpu_module._best_w                   = 0.0
    gpu_module._utilization              = 0.0


def _get_gauge(name):
    from prometheus_client import REGISTRY
    for metric in REGISTRY.collect():
        for sample in metric.samples:
            if sample.name == name:
                return sample.value
    return None


# ---------------------------------------------------------------------------
# Tests: init()
# ---------------------------------------------------------------------------
class TestInit(unittest.TestCase):

    def setUp(self):
        _reset_gpu_state()
        self.pynvml = sys.modules['pynvml']
        self.pynvml.nvmlDeviceGetTotalEnergyConsumption.reset_mock(side_effect=True)
        self.pynvml.nvmlDeviceGetTotalEnergyConsumption.return_value = 100_000
        self.pynvml.nvmlDeviceGetPowerManagementLimit.return_value   = 360_000

    def test_energy_counter_supported_returns_true(self):
        result = gpu_module.init()
        self.assertTrue(result)
        self.assertTrue(gpu_module._energy_counter_supported)
        self.assertEqual(_get_gauge('gpu_power_measurement_method'), 1.0)

    def test_energy_counter_not_supported_returns_false(self):
        self.pynvml.nvmlDeviceGetTotalEnergyConsumption.side_effect = \
            self.pynvml.NVMLError_NotSupported()
        result = gpu_module.init()
        self.assertFalse(result)
        self.assertFalse(gpu_module._energy_counter_supported)
        self.assertEqual(_get_gauge('gpu_power_measurement_method'), 0.0)

    def test_tdp_converted_from_mw_to_w(self):
        self.pynvml.nvmlDeviceGetPowerManagementLimit.return_value = 450_000
        gpu_module.init()
        self.assertAlmostEqual(gpu_module._tdp_watts, 450.0)
        self.assertAlmostEqual(_get_gauge('gpu_power_limit_watts'), 450.0)


# ---------------------------------------------------------------------------
# Tests: collect() -- energy counter path
# ---------------------------------------------------------------------------
class TestCollectEnergyCounter(unittest.TestCase):

    def setUp(self):
        _reset_gpu_state()
        self.pynvml = sys.modules['pynvml']
        self.pynvml.nvmlDeviceGetTotalEnergyConsumption.side_effect = None
        self.pynvml.nvmlDeviceGetTotalEnergyConsumption.return_value = 100_000
        self.pynvml.nvmlDeviceGetPowerManagementLimit.return_value   = 360_000
        self.pynvml.nvmlDeviceGetUtilizationRates.return_value       = MagicMock(gpu=50)
        gpu_module.init()

    def test_first_cycle_measured_is_zero(self):
        # No previous reading yet: measured_w stays 0, best falls back to TDP estimate.
        gpu_module.collect()
        self.assertEqual(_get_gauge('gpu_power_watts_measured'), 0.0)
        self.assertAlmostEqual(_get_gauge('gpu_power_watts'), 180.0)  # 360 * 0.5

    def test_second_cycle_computes_correct_delta(self):
        energy_seq = iter([100_000, 158_000])  # +58 000 mJ over 1 s = 58 W
        self.pynvml.nvmlDeviceGetTotalEnergyConsumption.side_effect = lambda h: next(energy_seq)

        with patch('collectors.gpu.time') as mock_time:
            mock_time.perf_counter.side_effect = [0.0, 1.0]
            gpu_module.collect()
            gpu_module.collect()

        self.assertAlmostEqual(_get_gauge('gpu_power_watts_measured'), 58.0, places=1)
        self.assertAlmostEqual(_get_gauge('gpu_power_watts'),          58.0, places=1)

    def test_negative_energy_delta_yields_zero(self):
        energy_seq = iter([200_000, 100_000])  # counter went backwards
        self.pynvml.nvmlDeviceGetTotalEnergyConsumption.side_effect = lambda h: next(energy_seq)

        with patch('collectors.gpu.time') as mock_time:
            mock_time.perf_counter.side_effect = [0.0, 1.0]
            gpu_module.collect()
            gpu_module.collect()

        self.assertEqual(_get_gauge('gpu_power_watts_measured'), 0.0)

    def test_zero_time_delta_no_division_error(self):
        energy_seq = iter([100_000, 110_000])
        self.pynvml.nvmlDeviceGetTotalEnergyConsumption.side_effect = lambda h: next(energy_seq)

        with patch('collectors.gpu.time') as mock_time:
            mock_time.perf_counter.side_effect = [0.0, 0.0]
            gpu_module.collect()
            try:
                gpu_module.collect()
            except ZeroDivisionError:
                self.fail("collect() raised ZeroDivisionError on zero time delta")

        self.assertEqual(_get_gauge('gpu_power_watts_measured'), 0.0)


# ---------------------------------------------------------------------------
# Tests: collect() -- TDP fallback path
# ---------------------------------------------------------------------------
class TestCollectTDPFallback(unittest.TestCase):

    def setUp(self):
        _reset_gpu_state()
        self.pynvml = sys.modules['pynvml']
        self.pynvml.nvmlDeviceGetTotalEnergyConsumption.side_effect = \
            self.pynvml.NVMLError_NotSupported()
        self.pynvml.nvmlDeviceGetPowerManagementLimit.return_value = 360_000
        gpu_module.init()

    def test_zero_utilization_gives_zero_estimate(self):
        self.pynvml.nvmlDeviceGetUtilizationRates.return_value = MagicMock(gpu=0)
        gpu_module.collect()
        self.assertAlmostEqual(_get_gauge('gpu_power_watts_estimated'), 0.0)
        self.assertAlmostEqual(_get_gauge('gpu_power_watts'), 0.0)

    def test_full_utilization_gives_tdp(self):
        self.pynvml.nvmlDeviceGetUtilizationRates.return_value = MagicMock(gpu=100)
        gpu_module.collect()
        self.assertAlmostEqual(_get_gauge('gpu_power_watts_estimated'), 360.0)
        self.assertAlmostEqual(_get_gauge('gpu_power_watts'), 360.0)

    def test_midpoint_utilization(self):
        self.pynvml.nvmlDeviceGetUtilizationRates.return_value = MagicMock(gpu=50)
        gpu_module.collect()
        self.assertAlmostEqual(_get_gauge('gpu_power_watts_estimated'), 180.0)

    def test_measured_gauge_stays_zero(self):
        self.pynvml.nvmlDeviceGetUtilizationRates.return_value = MagicMock(gpu=80)
        gpu_module.collect()
        self.assertEqual(_get_gauge('gpu_power_watts_measured'), 0.0)


# ---------------------------------------------------------------------------
# Tests: get_power_w() and get_utilization()
# ---------------------------------------------------------------------------
class TestGetPowerW(unittest.TestCase):

    def setUp(self):
        _reset_gpu_state()
        self.pynvml = sys.modules['pynvml']
        self.pynvml.nvmlDeviceGetPowerManagementLimit.return_value = 360_000

    def test_returns_zero_before_any_collect(self):
        # _best_w starts at 0.0; get_power_w() reads it directly (no REGISTRY scan)
        self.assertEqual(gpu_module.get_power_w(), 0.0)

    def test_returns_tdp_estimate_after_first_collect(self):
        # After first collect, no delta yet -> best_w = TDP estimate
        self.pynvml.nvmlDeviceGetTotalEnergyConsumption.side_effect = None
        self.pynvml.nvmlDeviceGetTotalEnergyConsumption.return_value = 100_000
        self.pynvml.nvmlDeviceGetUtilizationRates.return_value = MagicMock(gpu=30)
        gpu_module.init()
        with patch('collectors.gpu.time') as mock_time:
            mock_time.perf_counter.return_value = 0.0
            gpu_module.collect()
        # TDP * 30% = 360 * 0.30 = 108W
        self.assertAlmostEqual(gpu_module.get_power_w(), 108.0)

    def test_returns_measured_after_two_collects(self):
        # init() calls GetTotalEnergyConsumption once for the probe:
        # sequence needs 3 values: probe + collect1 + collect2.
        self.pynvml.nvmlDeviceGetTotalEnergyConsumption.side_effect = None
        energy_seq = iter([100_000, 100_000, 158_000])
        self.pynvml.nvmlDeviceGetTotalEnergyConsumption.side_effect = lambda h: next(energy_seq)
        self.pynvml.nvmlDeviceGetUtilizationRates.return_value = MagicMock(gpu=0)
        gpu_module.init()

        with patch('collectors.gpu.time') as mock_time:
            mock_time.perf_counter.side_effect = [0.0, 1.0]
            gpu_module.collect()
            gpu_module.collect()

        self.assertAlmostEqual(gpu_module.get_power_w(), 58.0, places=1)

    def test_get_utilization_reflects_collect(self):
        # get_utilization() reads _utilization set by collect()
        self.pynvml.nvmlDeviceGetTotalEnergyConsumption.side_effect = None
        self.pynvml.nvmlDeviceGetTotalEnergyConsumption.return_value = 100_000
        self.pynvml.nvmlDeviceGetUtilizationRates.return_value = MagicMock(gpu=75)
        gpu_module.init()
        with patch('collectors.gpu.time') as mock_time:
            mock_time.perf_counter.return_value = 0.0
            gpu_module.collect()
        self.assertEqual(gpu_module.get_utilization(), 75.0)


if __name__ == '__main__':
    unittest.main()
