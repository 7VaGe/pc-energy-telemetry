# collectors/gaming_session.py
# Traccia le sessioni gaming ricevendo il gioco rilevato da classifier.py
# (nessuna doppia scansione dei processi per ciclo).

import time
from prometheus_client import Counter, Gauge

SESSION_CLOSE_DELAY_S = 30

gaming_session_active     = Gauge('gaming_session_active',        'Gaming session active (1=yes)')
gaming_session_duration_s = Gauge('gaming_session_duration_s',    'Current gaming session duration (s)')
gaming_session_energy_kwh = Gauge('gaming_session_energy_kwh',    'Energy in current gaming session (kWh)')
gaming_session_cost_euro  = Gauge('gaming_session_cost_euro',     'Cost of current gaming session (EUR)')
gaming_session_game       = Gauge('gaming_session_detected_game', 'Active game process (1=active)', ['game'])

gaming_sessions_completed  = Counter('gaming_sessions_completed_total',   'Completed gaming sessions')
gaming_sessions_energy_kwh = Counter('gaming_sessions_energy_kwh_total',  'Total gaming energy (kWh)')
gaming_sessions_cost_euro  = Counter('gaming_sessions_cost_euro_total',   'Total gaming cost (EUR)')
gaming_sessions_duration_s = Counter('gaming_sessions_duration_s_total',  'Total gaming duration (s)')

_session_active = False
_session_start  = 0.0
_session_energy = 0.0
_session_cost   = 0.0
_last_seen_game = 0.0
_current_game   = ''


def _start_session(game: str):
    global _session_active, _session_start, _session_energy, _session_cost, _current_game
    _session_active = True
    _session_start  = time.time()
    _session_energy = 0.0
    _session_cost   = 0.0
    _current_game   = game
    gaming_session_active.set(1)
    gaming_session_game.labels(game=game).set(1)


def _close_session():
    global _session_active, _current_game
    if not _session_active:
        return
    duration = time.time() - _session_start
    gaming_sessions_completed.inc()
    gaming_sessions_energy_kwh.inc(_session_energy)
    gaming_sessions_cost_euro.inc(_session_cost)
    gaming_sessions_duration_s.inc(duration)
    if _current_game:
        gaming_session_game.labels(game=_current_game).set(0)
    _session_active = False
    _current_game   = ''
    gaming_session_active.set(0)
    gaming_session_duration_s.set(0)
    gaming_session_energy_kwh.set(0)
    gaming_session_cost_euro.set(0)


def collect(power_w: float, price_eur_kwh: float, game: str = ''):
    """
    Aggiorna il tracking della sessione gaming.
    Args:
        power_w:       potenza totale sistema (W)
        price_eur_kwh: tariffa attiva (EUR/kWh)
        game:          nome processo gioco da classifier.py ('' se nessuno)
    """
    global _session_active, _session_energy, _session_cost, _last_seen_game, _current_game

    if game:
        _last_seen_game = time.time()
        if not _session_active:
            _start_session(game)

    if _session_active:
        delta_kwh       = (power_w * 2.0) / 3600.0 / 1000.0
        delta_euro      = delta_kwh * price_eur_kwh
        _session_energy += delta_kwh
        _session_cost   += delta_euro
        duration         = time.time() - _session_start
        gaming_session_duration_s.set(duration)
        gaming_session_energy_kwh.set(_session_energy)
        gaming_session_cost_euro.set(_session_cost)

        if not game and (time.time() - _last_seen_game) > SESSION_CLOSE_DELAY_S:
            _close_session()
