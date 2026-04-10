# collectors/llm_stats.py
# Polls the LM Studio local server API to retrieve inference statistics.
# Uses the /api/v0/chat/completions endpoint which returns a 'stats' block
# containing tokens_per_second, time_to_first_token, and generation_time.
#
# Cost per token is derived as:
#   cost_per_token = (power_w / 1000) * (1 / tokens_per_second) / 3600 * price_eur_kwh
#
# This represents the energy cost of generating a single token at the
# current power draw and active tariff band.

import time
import requests
import logging
from prometheus_client import Gauge

log = logging.getLogger(__name__)

# Throttle: probe inference at most once every 60 seconds.
# llm_proxy.py handles real-time per-request stats; this module
# does periodic sampling only (tokens/s benchmark, TTFT, etc.)
PROBE_INTERVAL_S  = 60
_last_probe_time  = 0.0

LM_STUDIO_BASE_URL  = 'http://localhost:1234'
LM_STUDIO_STATS_EP  = f'{LM_STUDIO_BASE_URL}/api/v0/chat/completions'
LM_STUDIO_MODELS_EP = f'{LM_STUDIO_BASE_URL}/v1/models'

# Inference performance metrics
llm_tokens_per_second    = Gauge('llm_tokens_per_second',     'LLM inference speed (tokens/s)')
llm_time_to_first_token  = Gauge('llm_time_to_first_token_s', 'Time to first token in LLM inference (s)')
llm_generation_time      = Gauge('llm_generation_time_s',     'Total generation time for last LLM call (s)')
llm_total_tokens         = Gauge('llm_last_call_total_tokens', 'Total tokens in last LLM API call')

# Cost efficiency metrics
llm_cost_per_token_euro  = Gauge('llm_cost_per_token_euro',   'Estimated energy cost per token (EUR)')
llm_cost_per_1k_euro     = Gauge('llm_cost_per_1k_tokens_euro','Estimated energy cost per 1000 tokens (EUR)')

# Server state
llm_server_available     = Gauge('llm_server_available',       'LM Studio server reachable (1=yes, 0=no)')
llm_active_model         = Gauge('llm_active_model_loaded',    'Number of models loaded in LM Studio')

_last_stats = {}

def _get_active_model() -> str | None:
    # Returns the first available model id from LM Studio, or None if unavailable.
    try:
        r = requests.get(LM_STUDIO_MODELS_EP, timeout=2)
        models = r.json().get('data', [])
        llm_active_model.set(len(models))
        if models:
            return models[0]['id']
    except Exception:
        pass
    return None

def _probe_inference(model_id: str) -> dict:
    # Sends a minimal inference request to retrieve fresh stats.
    # Uses a very short max_tokens to minimize GPU load impact.
    payload = {
        'model':      model_id,
        'messages':   [{'role': 'user', 'content': 'x'}],
        'max_tokens': 3,
        'stream':     False,
    }
    r = requests.post(LM_STUDIO_STATS_EP, json=payload, timeout=10)
    return r.json()

def collect(power_w: float, price_eur_kwh: float, session: str):
    # power_w:        current total system power draw (W)
    # price_eur_kwh:  active tariff price (EUR/kWh)
    # session:        current session type

    global _last_stats, _last_probe_time

    # Only probe LM Studio when session is classified as LLM
    if session != 'llm':
        llm_server_available.set(0)
        return

    # Throttle: skip probe if called too soon since last run
    now = time.monotonic()
    if now - _last_probe_time < PROBE_INTERVAL_S:
        return
    _last_probe_time = now

    try:
        model_id = _get_active_model()
        if not model_id:
            llm_server_available.set(0)
            return

        llm_server_available.set(1)

        # Use cached stats if probe fails to avoid spamming the API
        data  = _probe_inference(model_id)
        stats = data.get('stats', {})
        usage = data.get('usage', {})

        if not stats:
            return

        _last_stats = stats

        tps   = stats.get('tokens_per_second', 0)
        ttft  = stats.get('time_to_first_token', 0)
        gt    = stats.get('generation_time', 0)
        total = usage.get('total_tokens', 0)

        llm_tokens_per_second.set(tps)
        llm_time_to_first_token.set(ttft)
        llm_generation_time.set(gt)
        llm_total_tokens.set(total)

        # Cost per token: energy to generate one token at current power draw
        # E_token (kWh) = P (W) / 1000 / tps / 3600
        if tps > 0:
            kwh_per_token      = (power_w / 1000.0) / tps / 3600.0
            cost_per_token     = kwh_per_token * price_eur_kwh
            llm_cost_per_token_euro.set(cost_per_token)
            llm_cost_per_1k_euro.set(cost_per_token * 1000)

    except Exception as e:
        log.warning(f"LLM stats collection failed: {e}")
        llm_server_available.set(0)