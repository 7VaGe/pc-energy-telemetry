# collectors/energy.py
# Tracks cumulative energy consumption (kWh) and estimated cost (EUR)
# broken down by session type (gaming, llm, idle).
#
# Power estimation: GPU (TDP * util%) + CPU (TDP * util%) + system baseline
# Baseline derived from hardware_profile.py based on detected components.
# Energy formula:  E (kWh) = P (W) * dt (s) / 3600 / 1000
# Cost formula:    C (EUR) = E (kWh) * price (EUR/kWh)
#
# Italian energy tariff bands:
#   F1 - weekdays 08:00-19:00                                  -> peak rate
#   F2 - weekdays 07:00-08:00, 19:00-23:00 + saturday 07:00-23:00 -> mid rate
#   F3 - nights + sunday                                        -> off-peak rate

import time
from datetime import datetime
from prometheus_client import Gauge, Counter
from collectors import hardware_profile

# --- Cumulative energy counters (kWh) ---
energy_total_kwh  = Counter('energy_kwh_total',  'Total energy consumed (kWh)')
energy_gaming_kwh = Counter('energy_kwh_gaming', 'Energy consumed during gaming sessions (kWh)')
energy_llm_kwh    = Counter('energy_kwh_llm',    'Energy consumed during LLM inference sessions (kWh)')
energy_idle_kwh   = Counter('energy_kwh_idle',   'Energy consumed during idle sessions (kWh)')

# --- Cumulative cost counters (EUR) ---
cost_total_euro   = Counter('cost_euro_total',   'Total estimated energy cost (EUR)')
cost_gaming_euro  = Counter('cost_euro_gaming',  'Estimated energy cost during gaming sessions (EUR)')
cost_llm_euro     = Counter('cost_euro_llm',     'Estimated energy cost during LLM inference sessions (EUR)')
cost_idle_euro    = Counter('cost_euro_idle',    'Estimated energy cost during idle sessions (EUR)')

# --- Instantaneous gauges for dashboard readability ---
power_total_watts = Gauge('power_total_watts_estimated', 'Current total system power draw estimate (W)')
tariff_active     = Gauge('energy_tariff_active',        'Active Italian tariff band (1=F1, 2=F2, 3=F3)')
price_active_euro = Gauge('energy_price_euro_per_kwh',   'Active energy price (EUR/kWh)')

# --- Italian tariff rates (EUR/kWh) ---
# Source: ARERA standard reference prices
TARIFF = {
    'F1': 0.28,
    'F2': 0.22,
    'F3': 0.16,
}

_prev_time    = None

# In-memory state exposed directly by get_total_power_w() / get_price()
_total_power_w   = 0.0
_price_eur_kwh   = TARIFF['F1']


def _get_tariff_band() -> tuple[str, float]:
    # Determine the active Italian tariff band based on current time.
    # F1: Mon-Fri 08:00-19:00
    # F2: Mon-Fri 07:00-08:00 and 19:00-23:00, Sat 07:00-23:00
    # F3: all other times (nights, Sundays, holidays)
    now     = datetime.now()
    weekday = now.weekday()
    hour    = now.hour

    if weekday == 6:
        return 'F3', TARIFF['F3']

    if weekday == 5:
        if 7 <= hour < 23:
            return 'F2', TARIFF['F2']
        return 'F3', TARIFF['F3']

    if 8 <= hour < 19:
        return 'F1', TARIFF['F1']
    if (7 <= hour < 8) or (19 <= hour < 23):
        return 'F2', TARIFF['F2']
    return 'F3', TARIFF['F3']


def collect(session: str, gpu_power_w: float, cpu_power_w: float):
    # Called every scrape cycle.
    # session:     current session type ('idle', 'gaming', 'llm')
    # gpu_power_w: GPU power in Watts (from energy counter or TDP estimate)
    # cpu_power_w: estimated CPU power in Watts

    global _prev_time, _total_power_w, _price_eur_kwh

    now = time.time()

    if _prev_time is None:
        _prev_time = now
        return

    delta_s    = now - _prev_time
    _prev_time = now

    # Total power includes dynamic GPU/CPU load + fixed system baseline
    total_w   = gpu_power_w + cpu_power_w + hardware_profile.get()
    delta_kwh = (total_w * delta_s) / 3600.0 / 1000.0

    band, price = _get_tariff_band()
    delta_euro  = delta_kwh * price

    power_total_watts.set(total_w)
    tariff_active.set({'F1': 1, 'F2': 2, 'F3': 3}[band])
    price_active_euro.set(price)

    # Update in-memory state for get_total_power_w() / get_price()
    _total_power_w = total_w
    _price_eur_kwh = price

    energy_total_kwh.inc(delta_kwh)
    cost_total_euro.inc(delta_euro)

    if session == 'gaming':
        energy_gaming_kwh.inc(delta_kwh)
        cost_gaming_euro.inc(delta_euro)
    elif session == 'llm':
        energy_llm_kwh.inc(delta_kwh)
        cost_llm_euro.inc(delta_euro)
    else:
        energy_idle_kwh.inc(delta_kwh)
        cost_idle_euro.inc(delta_euro)


def get_total_power_w() -> float:
    # Returns the last computed total system power for downstream consumers.
    # Reads from in-memory state set by collect() -- no REGISTRY scan.
    return _total_power_w


def get_price() -> float:
    # Returns the active tariff price (EUR/kWh) for downstream consumers.
    # Reads from in-memory state set by collect() -- no REGISTRY scan.
    return _price_eur_kwh
