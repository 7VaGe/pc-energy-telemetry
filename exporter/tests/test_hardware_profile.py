# tests/test_hardware_profile.py
# Unit tests for collectors/hardware_profile.py
#
# Validates component constants, PSU efficiency formula, gauge publication,
# and the get() accessor. No reload between tests (avoids Prometheus
# duplicate-registration errors from module-level Gauge declarations).

import unittest
from unittest.mock import patch
import collectors.hardware_profile as hw_module
from prometheus_client import REGISTRY


def _get_gauge(name):
    for metric in REGISTRY.collect():
        for sample in metric.samples:
            if sample.name == name:
                return sample.value
    return None


# ---------------------------------------------------------------------------
# Tests: component power constants
# ---------------------------------------------------------------------------
class TestComponentConstants(unittest.TestCase):

    def test_ddr5_stick_count_is_two(self):
        self.assertEqual(hw_module.DDR5_STICKS, 2)

    def test_ddr5_per_stick_positive(self):
        self.assertGreater(hw_module.DDR5_PER_STICK_WATTS, 0)

    def test_ddr5_total_is_six_watts(self):
        total = hw_module.DDR5_STICKS * hw_module.DDR5_PER_STICK_WATTS
        self.assertAlmostEqual(total, 6.0)

    def test_nvme_s880_in_plausible_range(self):
        self.assertGreater(hw_module.NVME_S880_WATTS, 1.0)
        self.assertLess   (hw_module.NVME_S880_WATTS, 6.0)

    def test_nvme_shpp41_in_plausible_range(self):
        self.assertGreater(hw_module.NVME_SHPP41_WATTS, 1.0)
        self.assertLess   (hw_module.NVME_SHPP41_WATTS, 6.0)

    def test_am5_platform_within_datasheet_range(self):
        # AMD AM5 documented idle overhead: 30-45 W
        self.assertGreaterEqual(hw_module.AM5_PLATFORM_WATTS, 30.0)
        self.assertLessEqual   (hw_module.AM5_PLATFORM_WATTS, 45.0)

    def test_psu_efficiency_is_valid_fraction(self):
        self.assertGreater(hw_module.PSU_EFFICIENCY_IDLE, 0.0)
        self.assertLess   (hw_module.PSU_EFFICIENCY_IDLE, 1.0)

    def test_psu_efficiency_in_platinum_range(self):
        # 80+ Platinum at light load: 85-92 %
        self.assertGreaterEqual(hw_module.PSU_EFFICIENCY_IDLE, 0.85)
        self.assertLessEqual   (hw_module.PSU_EFFICIENCY_IDLE, 0.92)

    def test_kraken_pump_watts_positive(self):
        self.assertGreater(hw_module.KRAKEN_PUMP_WATTS, 0.0)

    def test_corsair_fan_count_is_five(self):
        self.assertEqual(hw_module.CORSAIR_LX140_COUNT, 5)


# ---------------------------------------------------------------------------
# Tests: init() formula and gauge publication
#
# All tests in this class pin _is_original_hardware() to True so that
# the validated constants are always used, regardless of the test runner's
# actual CPU. This keeps assertions deterministic across environments.
# ---------------------------------------------------------------------------
class TestBaselineFormula(unittest.TestCase):

    def setUp(self):
        self._patcher = patch(
            'collectors.hardware_profile._is_original_hardware',
            return_value=True
        )
        self._patcher.start()

    def tearDown(self):
        self._patcher.stop()

    def test_init_returns_positive_float(self):
        total = hw_module.init()
        self.assertIsInstance(total, float)
        self.assertGreater(total, 0.0)

    def test_init_result_matches_manual_calculation(self):
        ram_w      = hw_module.DDR5_STICKS * hw_module.DDR5_PER_STICK_WATTS
        storage_w  = hw_module.NVME_S880_WATTS + hw_module.NVME_SHPP41_WATTS
        platform_w = hw_module.MOTHERBOARD_WATTS + hw_module.AM5_PLATFORM_WATTS
        cooling_w  = (hw_module.KRAKEN_PUMP_WATTS +
                      hw_module.KRAKEN_LCD_WATTS +
                      hw_module.CORSAIR_LX140_COUNT * hw_module.CORSAIR_LX140_IDLE_W)
        subtotal   = ram_w + storage_w + platform_w + cooling_w
        psu_loss   = subtotal * (1.0 / hw_module.PSU_EFFICIENCY_IDLE - 1.0)
        expected   = subtotal + psu_loss

        result = hw_module.init()
        self.assertAlmostEqual(result, expected, places=2)

    def test_psu_loss_is_positive(self):
        hw_module.init()
        psu_loss = _get_gauge('baseline_psu_loss_watts')
        self.assertGreater(psu_loss, 0.0)

    def test_baseline_in_calibrated_model_range(self):
        # Model baseline (excl. GPU idle floor): expected 70-100 W.
        total = hw_module.init()
        self.assertGreater(total, 70.0)
        self.assertLess   (total, 100.0)

    def test_all_gauges_published_and_positive(self):
        hw_module.init()
        for name in ('baseline_power_watts', 'baseline_ram_watts',
                     'baseline_storage_watts', 'baseline_platform_watts',
                     'baseline_cooling_watts', 'baseline_psu_loss_watts'):
            val = _get_gauge(name)
            self.assertIsNotNone(val,     msg=f"{name} not published")
            self.assertGreater  (val, 0.0, msg=f"{name} should be > 0")

    def test_get_returns_same_value_as_init(self):
        expected = hw_module.init()
        self.assertAlmostEqual(hw_module.get(), expected, places=2)

    def test_component_gauges_sum_to_subtotal(self):
        hw_module.init()
        ram_w      = _get_gauge('baseline_ram_watts')
        storage_w  = _get_gauge('baseline_storage_watts')
        platform_w = _get_gauge('baseline_platform_watts')
        cooling_w  = _get_gauge('baseline_cooling_watts')
        psu_loss_w = _get_gauge('baseline_psu_loss_watts')
        total_w    = _get_gauge('baseline_power_watts')
        self.assertAlmostEqual(
            ram_w + storage_w + platform_w + cooling_w + psu_loss_w,
            total_w,
            places=2
        )


if __name__ == '__main__':
    unittest.main()
