# tests/test_gpu_collector.py
# Unit tests for collectors/gpu.py
#
# gpu.py is now a thin Prometheus publishing layer; hardware access lives
# in the provider layer. Tests mock collectors.providers.gpu_factory.build
# to inject a controlled provider, so no real GPU or NVML is required.
#
# Prometheus Gauges are module-level singletons: tests reset only the
# private state variables to avoid CollectorRegistry duplicate errors.

import unittest
from unittest.mock import MagicMock, patch

import collectors.gpu as gpu_module
from collectors.providers.base import GPUSample


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_sample(
    power_w=0.0, utilization_pct=0.0,
    memory_used_mb=0.0, memory_total_mb=16384.0,
    temperature_c=40.0, clock_mhz=2400.0,
    measured_valid=False,
):
    return GPUSample(
        power_w=power_w,
        utilization_pct=utilization_pct,
        memory_used_mb=memory_used_mb,
        memory_total_mb=memory_total_mb,
        temperature_c=temperature_c,
        clock_mhz=clock_mhz,
        measured_valid=measured_valid,
    )


def _make_provider(method_label="nvml_energy_counter", tdp_watts=360.0, sample=None):
    provider = MagicMock()
    provider.METHOD_LABEL = method_label
    provider.tdp_watts = tdp_watts
    provider.collect.return_value = sample if sample is not None else _make_sample()
    return provider


def _reset_gpu_state():
    gpu_module._provider    = None
    gpu_module._best_w      = 0.0
    gpu_module._utilization = 0.0


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

    def test_measured_provider_returns_true(self):
        provider = _make_provider(method_label="nvml_energy_counter", tdp_watts=360.0)
        with patch('collectors.providers.gpu_factory.build', return_value=provider):
            result = gpu_module.init()
        self.assertTrue(result)
        self.assertEqual(_get_gauge('gpu_power_measurement_method'), 1.0)

    def test_tdp_provider_returns_false(self):
        provider = _make_provider(method_label="tdp_estimate", tdp_watts=360.0)
        with patch('collectors.providers.gpu_factory.build', return_value=provider):
            result = gpu_module.init()
        self.assertFalse(result)
        self.assertEqual(_get_gauge('gpu_power_measurement_method'), 0.0)

    def test_power_limit_published_from_provider_tdp(self):
        provider = _make_provider(method_label="nvml_power_usage", tdp_watts=450.0)
        with patch('collectors.providers.gpu_factory.build', return_value=provider):
            gpu_module.init()
        self.assertAlmostEqual(_get_gauge('gpu_power_limit_watts'), 450.0)


# ---------------------------------------------------------------------------
# Tests: collect() -- measured path (sample.measured_valid = True)
# ---------------------------------------------------------------------------
class TestCollectMeasuredPath(unittest.TestCase):

    def setUp(self):
        _reset_gpu_state()
        sample   = _make_sample(power_w=58.0, utilization_pct=50.0, measured_valid=True)
        provider = _make_provider(method_label="nvml_energy_counter", tdp_watts=360.0, sample=sample)
        with patch('collectors.providers.gpu_factory.build', return_value=provider):
            gpu_module.init()

    def test_best_watts_equals_measured_power(self):
        gpu_module.collect()
        self.assertAlmostEqual(_get_gauge('gpu_power_watts'), 58.0, places=1)

    def test_measured_gauge_equals_sample_power(self):
        gpu_module.collect()
        self.assertAlmostEqual(_get_gauge('gpu_power_watts_measured'), 58.0, places=1)

    def test_estimated_gauge_uses_tdp_formula(self):
        # 360 * 50% = 180 W
        gpu_module.collect()
        self.assertAlmostEqual(_get_gauge('gpu_power_watts_estimated'), 180.0, places=1)

    def test_in_memory_state_updated(self):
        gpu_module.collect()
        self.assertAlmostEqual(gpu_module.get_power_w(), 58.0, places=1)
        self.assertAlmostEqual(gpu_module.get_utilization(), 50.0, places=1)


# ---------------------------------------------------------------------------
# Tests: collect() -- TDP fallback path (sample.measured_valid = False)
# ---------------------------------------------------------------------------
class TestCollectTDPFallback(unittest.TestCase):

    def setUp(self):
        _reset_gpu_state()

    def _init_with(self, utilization_pct, tdp_watts=360.0):
        power = tdp_watts * utilization_pct / 100.0
        sample   = _make_sample(power_w=power, utilization_pct=utilization_pct, measured_valid=False)
        provider = _make_provider(method_label="tdp_estimate", tdp_watts=tdp_watts, sample=sample)
        with patch('collectors.providers.gpu_factory.build', return_value=provider):
            gpu_module.init()

    def test_measured_gauge_is_zero_on_tdp_path(self):
        self._init_with(50.0)
        gpu_module.collect()
        self.assertEqual(_get_gauge('gpu_power_watts_measured'), 0.0)

    def test_best_equals_tdp_estimate(self):
        self._init_with(50.0)
        gpu_module.collect()
        # 360 * 50% = 180 W
        self.assertAlmostEqual(_get_gauge('gpu_power_watts'), 180.0, places=1)

    def test_zero_utilization_gives_zero_power(self):
        self._init_with(0.0)
        gpu_module.collect()
        self.assertAlmostEqual(_get_gauge('gpu_power_watts'), 0.0, places=1)

    def test_full_utilization_gives_tdp(self):
        self._init_with(100.0, tdp_watts=360.0)
        gpu_module.collect()
        self.assertAlmostEqual(_get_gauge('gpu_power_watts'), 360.0, places=1)


# ---------------------------------------------------------------------------
# Tests: get_power_w() and get_utilization() state getters
# ---------------------------------------------------------------------------
class TestGetters(unittest.TestCase):

    def setUp(self):
        _reset_gpu_state()

    def test_get_power_w_zero_before_init(self):
        self.assertEqual(gpu_module.get_power_w(), 0.0)

    def test_get_utilization_zero_before_collect(self):
        self.assertEqual(gpu_module.get_utilization(), 0.0)

    def test_get_power_w_reflects_collect(self):
        sample   = _make_sample(power_w=120.0, utilization_pct=33.0, measured_valid=True)
        provider = _make_provider(sample=sample)
        with patch('collectors.providers.gpu_factory.build', return_value=provider):
            gpu_module.init()
        gpu_module.collect()
        self.assertAlmostEqual(gpu_module.get_power_w(), 120.0, places=1)

    def test_get_utilization_reflects_collect(self):
        sample   = _make_sample(power_w=0.0, utilization_pct=75.0, measured_valid=False)
        provider = _make_provider(tdp_watts=360.0, sample=sample)
        with patch('collectors.providers.gpu_factory.build', return_value=provider):
            gpu_module.init()
        gpu_module.collect()
        self.assertEqual(gpu_module.get_utilization(), 75.0)


if __name__ == '__main__':
    unittest.main()
