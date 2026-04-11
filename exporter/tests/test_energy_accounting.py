# tests/test_energy_accounting.py
# Unit tests for collectors/energy.py
#
# Covers: Italian tariff band selection (F1/F2/F3),
# kWh and cost accumulation formula, and session routing.
#
# hardware_profile.get() is patched per-test via unittest.mock so the real
# module is never replaced in sys.modules (avoids cross-test contamination).
# Prometheus Counters are cumulative: assertions use before/after deltas.

import sys
import unittest
from datetime import datetime
from unittest.mock import patch

from prometheus_client import REGISTRY
import collectors.energy as energy_module


def _get_counter(name):
    # In prometheus_client 0.20+, Counter('foo_total') strips _total -> metric.name='foo',
    # sample.name='foo_total'. Counter('foo') keeps metric.name='foo', sample.name='foo_total'.
    # Try exact sample name first, then with _total appended.
    candidates = {name, name + '_total'}
    for metric in REGISTRY.collect():
        for sample in metric.samples:
            if sample.name in candidates:
                return sample.value
    return 0.0


def _reset_energy():
    energy_module._prev_time = None


def _monday(hour):
    return datetime(2024, 1, 1, hour, 0)   # 2024-01-01 is a Monday


def _weekday(day_offset, hour):
    return datetime(2024, 1, 1 + day_offset, hour, 0)


# ---------------------------------------------------------------------------
# Tests: Italian tariff band logic
# ---------------------------------------------------------------------------
class TestTariffBand(unittest.TestCase):

    def _band(self, dt):
        with patch('collectors.energy.datetime') as mock_dt:
            mock_dt.now.return_value = dt
            band, _ = energy_module._get_tariff_band()
        return band

    def test_f1_weekday_midday(self):
        self.assertEqual(self._band(_monday(10)), 'F1')

    def test_f1_weekday_boundary_start(self):
        self.assertEqual(self._band(_monday(8)), 'F1')

    def test_f1_weekday_boundary_end(self):
        self.assertEqual(self._band(_monday(18)), 'F1')

    def test_f2_weekday_morning_shoulder(self):
        self.assertEqual(self._band(_monday(7)), 'F2')

    def test_f2_weekday_evening_shoulder(self):
        self.assertEqual(self._band(_monday(20)), 'F2')

    def test_f2_saturday_daytime(self):
        self.assertEqual(self._band(_weekday(5, 12)), 'F2')

    def test_f3_weekday_night(self):
        self.assertEqual(self._band(_monday(3)), 'F3')

    def test_f3_sunday(self):
        self.assertEqual(self._band(_weekday(6, 14)), 'F3')

    def test_f3_saturday_night(self):
        self.assertEqual(self._band(_weekday(5, 0)), 'F3')


# ---------------------------------------------------------------------------
# Tests: kWh formula and cost accumulation (delta-based)
# ---------------------------------------------------------------------------
class TestEnergyAccumulation(unittest.TestCase):

    def setUp(self):
        _reset_energy()

    def _run_two_cycles(self, session, gpu_w, cpu_w, delta_s, hour=10):
        dt = _monday(hour)
        with patch('collectors.energy.hardware_profile') as mock_hw, \
             patch('collectors.energy.time') as mt, \
             patch('collectors.energy.datetime') as md:
            mock_hw.get.return_value = 0.0
            md.now.return_value = dt
            mt.time.return_value = 0.0
            energy_module.collect(session=session, gpu_power_w=0, cpu_power_w=0)
            mt.time.return_value = delta_s
            energy_module.collect(session=session, gpu_power_w=gpu_w, cpu_power_w=cpu_w)

    def test_kwh_formula_100w_for_one_hour(self):
        # 100 W * 3600 s / 3_600_000 = 0.1 kWh
        before = _get_counter('energy_kwh_total')
        self._run_two_cycles('idle', gpu_w=60.0, cpu_w=40.0, delta_s=3600.0)
        delta = _get_counter('energy_kwh_total') - before
        self.assertAlmostEqual(delta, 0.1, places=5)

    def test_cost_f1_rate(self):
        # 0.1 kWh * 0.28 EUR/kWh = 0.028 EUR  (Monday 10:00 = F1)
        before = _get_counter('cost_euro_total')
        self._run_two_cycles('idle', gpu_w=100.0, cpu_w=0.0, delta_s=3600.0, hour=10)
        delta = _get_counter('cost_euro_total') - before
        self.assertAlmostEqual(delta, 0.028, places=4)

    def test_session_routing_llm_increments_only_llm(self):
        before_llm    = _get_counter('energy_kwh_llm')
        before_gaming = _get_counter('energy_kwh_gaming')
        self._run_two_cycles('llm', gpu_w=300.0, cpu_w=0.0, delta_s=1.0)
        self.assertGreater(_get_counter('energy_kwh_llm')    - before_llm,    0.0)
        self.assertAlmostEqual(_get_counter('energy_kwh_gaming') - before_gaming, 0.0)

    def test_session_routing_gaming_increments_only_gaming(self):
        before_gaming = _get_counter('energy_kwh_gaming')
        before_llm    = _get_counter('energy_kwh_llm')
        self._run_two_cycles('gaming', gpu_w=300.0, cpu_w=0.0, delta_s=1.0)
        self.assertGreater(_get_counter('energy_kwh_gaming') - before_gaming, 0.0)
        self.assertAlmostEqual(_get_counter('energy_kwh_llm') - before_llm,   0.0)

    def test_first_cycle_records_no_energy(self):
        before = _get_counter('energy_kwh_total')
        with patch('collectors.energy.hardware_profile') as mock_hw, \
             patch('collectors.energy.time') as mt, \
             patch('collectors.energy.datetime') as md:
            mock_hw.get.return_value = 0.0
            md.now.return_value = _monday(10)
            mt.time.return_value = 0.0
            energy_module.collect(session='idle', gpu_power_w=100.0, cpu_power_w=0.0)
        self.assertAlmostEqual(_get_counter('energy_kwh_total'), before)


if __name__ == '__main__':
    unittest.main()
