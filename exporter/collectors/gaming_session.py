# collectors/gaming_session.py
# Tracks gaming sessions based on active process detection.
# A session starts when a known gaming process is detected and ends
# when no gaming process has been running for SESSION_CLOSE_DELAY_S seconds.
#
# Per-session metrics: duration, energy consumed, estimated cost.
# Historical metrics: total sessions, total energy, total cost.

import time
import psutil
from prometheus_client import Counter, Gauge

# Known gaming processes (must match classifier.py)
GAMING_PROCESSES = {
    'league of legends.exe',
    'leagueclient.exe',
    'witcher3.exe',
    'cyberpunk2077.exe',
    'cs2.exe',
    'valorant.exe',
    'fortnite.exe',
    'eldenring.exe',
}

SESSION_CLOSE_DELAY_S = 30  # seconds after process exit before session closes

# --- Current session metrics ---
gaming_session_active      = Gauge('gaming_session_active',
                                   'Whether a gaming session is currently active (1=yes)')
gaming_session_duration_s  = Gauge('gaming_session_duration_s',
                                   'Duration of the current gaming session (s)')
gaming_session_energy_kwh  = Gauge('gaming_session_energy_kwh',
                                   'Energy consumed in the current gaming session (kWh)')
gaming_session_cost_euro   = Gauge('gaming_session_cost_euro',
                                   'Energy cost of the current gaming session (EUR)')
gaming_session_game        = Gauge('gaming_session_detected_game',
                                   'Currently detected game process (1=active)',
                                   ['game'])

# --- Historical metrics ---
gaming_sessions_completed  = Counter('gaming_sessions_completed_total',
                                     'Total number of completed gaming sessions')
gaming_sessions_energy_kwh = Counter('gaming_sessions_energy_kwh_total',
                                     'Total energy consumed across all gaming sessions (kWh)')
gaming_sessions_cost_euro  = Counter('gaming_sessions_cost_euro_total',
                                     'Total energy cost across all gaming sessions (EUR)')
gaming_sessions_duration_s = Counter('gaming_sessions_duration_s_total',
                                     'Total duration of all gaming sessions (s)')

# Session state
_session_active     = False
_session_start      = 0.0
_session_energy     = 0.0
_session_cost       = 0.0
_last_seen_game     = 0.0
_current_game       = ''

def _get_active_game() -> str:
    # Returns the name of the first detected gaming process, or empty string.
    try:
        for proc in psutil.process_iter(['name']):
            name = proc.info['name'].lower()
            if name in GAMING_PROCESSES:
                return name
    except Exception:
        pass
    return ''

def _start_session(game: str):
    global _session_active, _session_start, _session_energy
    global _session_cost, _current_game
    _session_active = True
    _session_start  = time.time()
    _session_energy = 0.0
    _session_cost   = 0.0
    _current_game   = game
    gaming_session_active.set(1)
    gaming_session_detected_game = game

def _close_session():
    global _session_active, _current_game
    if not _session_active:
        return
    duration = time.time() - _session_start
    gaming_sessions_completed.inc()
    gaming_sessions_energy_kwh.inc(_session_energy)
    gaming_sessions_cost_euro.inc(_session_cost)
    gaming_sessions_duration_s.inc(duration)
    _session_active = False
    _current_game   = ''
    gaming_session_active.set(0)
    gaming_session_duration_s.set(0)
    gaming_session_energy_kwh.set(0)
    gaming_session_cost_euro.set(0)

def collect(power_w: float, price_eur_kwh: float):
    global _session_active, _session_energy, _session_cost
    global _last_seen_game, _current_game

    game = _get_active_game()

    if game:
        _last_seen_game = time.time()
        if not _session_active:
            _start_session(game)

    if _session_active:
        # Accumulate energy for this scrape interval (2s)
        delta_kwh     = (power_w * 2.0) / 3600.0 / 1000.0
        delta_euro    = delta_kwh * price_eur_kwh
        _session_energy += delta_kwh
        _session_cost   += delta_euro

        duration = time.time() - _session_start
        gaming_session_duration_s.set(duration)
        gaming_session_energy_kwh.set(_session_energy)
        gaming_session_cost_euro.set(_session_cost)

        # Close session if no game detected for SESSION_CLOSE_DELAY_S
        if not game and (time.time() - _last_seen_game) > SESSION_CLOSE_DELAY_S:
            _close_session()