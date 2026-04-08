# collectors/llm_proxy.py
# HTTP proxy that intercepts LM Studio API requests to measure
# per-request and per-session energy consumption and cost.
#
# Architecture:
#   Client → proxy (port 1235) → LM Studio (port 1234)
#
# Each intercepted /v1/chat/completions request records:
#   - prompt tokens, completion tokens, total tokens
#   - tokens per second (from LM Studio stats block or derived from latency)
#   - wall-clock latency
#   - energy consumed during inference
#   - estimated cost in EUR
#
# Session tracking:
#   A session starts when the first request arrives and ends when
#   no requests are received for SESSION_IDLE_TIMEOUT_S seconds.

import threading
import time
import json
import requests
from http.server import HTTPServer, BaseHTTPRequestHandler
from prometheus_client import Counter, Gauge

LM_STUDIO_URL        = 'http://localhost:1234'
PROXY_PORT           = 1235
SESSION_IDLE_TIMEOUT = 300

# --- Per-request metrics ---
llm_request_total         = Counter('llm_request_total',
                                    'Total number of LLM inference requests intercepted')
llm_request_tokens_total  = Counter('llm_request_tokens_total',
                                    'Total tokens generated across all requests')
llm_request_prompt_tokens = Counter('llm_request_prompt_tokens_total',
                                    'Total prompt tokens across all requests')
llm_request_cost_euro     = Counter('llm_request_cost_euro_total',
                                    'Total energy cost of all LLM requests (EUR)')
llm_request_energy_kwh    = Counter('llm_request_energy_kwh_total',
                                    'Total energy consumed by LLM requests (kWh)')

llm_last_request_tokens  = Gauge('llm_last_request_tokens',
                                 'Tokens generated in the last LLM request')
llm_last_request_cost    = Gauge('llm_last_request_cost_euro',
                                 'Energy cost of the last LLM request (EUR)')
llm_last_request_energy  = Gauge('llm_last_request_energy_kwh',
                                 'Energy consumed by the last LLM request (kWh)')
llm_last_request_tps     = Gauge('llm_last_request_tokens_per_second',
                                 'Tokens per second of the last LLM request')
llm_last_request_latency = Gauge('llm_last_request_latency_s',
                                 'Wall-clock latency of the last LLM request (s)')

# --- Per-session metrics ---
llm_session_active           = Gauge('llm_session_active',
                                     'Whether an LLM session is currently active (1=yes)')
llm_session_requests         = Gauge('llm_session_request_count',
                                     'Number of requests in the current LLM session')
llm_session_tokens           = Gauge('llm_session_tokens_total',
                                     'Total tokens generated in the current session')
llm_session_cost_euro        = Gauge('llm_session_cost_euro',
                                     'Total energy cost of the current LLM session (EUR)')
llm_session_energy_kwh       = Gauge('llm_session_energy_kwh',
                                     'Total energy consumed in the current session (kWh)')
llm_session_duration_s       = Gauge('llm_session_duration_s',
                                     'Duration of the current LLM session (s)')
llm_sessions_completed       = Counter('llm_sessions_completed_total',
                                       'Total number of completed LLM sessions')
llm_sessions_cost_euro_total = Counter('llm_sessions_cost_euro_completed_total',
                                       'Total cost of all completed LLM sessions (EUR)')
llm_sessions_tokens_total    = Counter('llm_sessions_tokens_completed_total',
                                       'Total tokens across all completed LLM sessions')

# Shared state
_lock          = threading.Lock()
_power_w       = 0.0
_price_eur_kwh = 0.28

# Session state
_session_active      = False
_session_start_time  = 0.0
_session_requests    = 0
_session_tokens      = 0
_session_cost        = 0.0
_session_energy      = 0.0
_session_last_active = 0.0
_session_timer       = None


def update_power(power_w: float, price_eur_kwh: float):
    # Called by main.py every scrape cycle to keep power/price current.
    global _power_w, _price_eur_kwh
    with _lock:
        _power_w       = power_w
        _price_eur_kwh = price_eur_kwh


def _start_session():
    global _session_active, _session_start_time, _session_requests
    global _session_tokens, _session_cost, _session_energy, _session_last_active
    _session_active      = True
    _session_start_time  = time.time()
    _session_requests    = 0
    _session_tokens      = 0
    _session_cost        = 0.0
    _session_energy      = 0.0
    _session_last_active = time.time()
    llm_session_active.set(1)


def _close_session():
    global _session_active
    if not _session_active:
        return
    _session_active = False
    llm_sessions_completed.inc()
    llm_sessions_cost_euro_total.inc(_session_cost)
    llm_sessions_tokens_total.inc(_session_tokens)
    llm_session_active.set(0)
    llm_session_requests.set(0)
    llm_session_tokens.set(0)
    llm_session_cost_euro.set(0)
    llm_session_energy_kwh.set(0)
    llm_session_duration_s.set(0)


def _schedule_session_timeout():
    global _session_timer
    if _session_timer:
        _session_timer.cancel()
    _session_timer = threading.Timer(SESSION_IDLE_TIMEOUT, _close_session)
    _session_timer.daemon = True
    _session_timer.start()


def _record_request(completion_tokens: int, prompt_tokens: int,
                    tps: float, latency_s: float, generation_time_s: float):
    global _session_requests, _session_tokens, _session_cost, _session_energy
    global _session_last_active

    with _lock:
        power_w       = _power_w
        price_eur_kwh = _price_eur_kwh

    energy_kwh = (power_w * generation_time_s) / 3600.0 / 1000.0
    cost_euro  = energy_kwh * price_eur_kwh

    llm_last_request_tokens.set(completion_tokens)
    llm_last_request_cost.set(cost_euro)
    llm_last_request_energy.set(energy_kwh)
    llm_last_request_tps.set(tps)
    llm_last_request_latency.set(latency_s)

    llm_request_total.inc()
    llm_request_tokens_total.inc(completion_tokens)
    llm_request_prompt_tokens.inc(prompt_tokens)
    llm_request_cost_euro.inc(cost_euro)
    llm_request_energy_kwh.inc(energy_kwh)

    if not _session_active:
        _start_session()

    _session_requests    += 1
    _session_tokens      += completion_tokens
    _session_cost        += cost_euro
    _session_energy      += energy_kwh
    _session_last_active  = time.time()

    duration = time.time() - _session_start_time
    llm_session_requests.set(_session_requests)
    llm_session_tokens.set(_session_tokens)
    llm_session_cost_euro.set(_session_cost)
    llm_session_energy_kwh.set(_session_energy)
    llm_session_duration_s.set(duration)

    _schedule_session_timeout()


class ProxyHandler(BaseHTTPRequestHandler):

    def log_message(self, format, *args):
        pass

    def _proxy_request(self, body: bytes):
        url     = f"{LM_STUDIO_URL}{self.path}"
        headers = {k: v for k, v in self.headers.items()
                   if k.lower() not in ('host', 'content-length')}
        t_start = time.time()
        resp    = requests.post(url, data=body, headers=headers, timeout=120)
        latency = time.time() - t_start
        return resp.status_code, resp.content, resp.headers, latency

    def do_POST(self):
        length = int(self.headers.get('Content-Length', 0))
        body   = self.rfile.read(length)

        status, resp_body, resp_headers, latency = self._proxy_request(body)

        if 'completions' in self.path:
            try:
                data  = json.loads(resp_body)
                usage = data.get('usage', {})
                stats = data.get('stats', {})
                c_tok = usage.get('completion_tokens', 0)
                p_tok = usage.get('prompt_tokens', 0)

                gen_t = stats.get('generation_time', 0.0) or latency
                tps   = stats.get('tokens_per_second', 0.0)
                if tps == 0.0 and gen_t > 0 and c_tok > 0:
                    tps = c_tok / gen_t

                _record_request(c_tok, p_tok, tps, latency, gen_t)
            except Exception:
                pass

        self.send_response(status)
        for key, val in resp_headers.items():
            if key.lower() in ('content-type', 'content-length'):
                self.send_header(key, val)
        self.end_headers()
        self.wfile.write(resp_body)

    def do_GET(self):
        url  = f"{LM_STUDIO_URL}{self.path}"
        resp = requests.get(url, timeout=10)
        self.send_response(resp.status_code)
        self.send_header('Content-Type',
                         resp.headers.get('Content-Type', 'application/json'))
        self.end_headers()
        self.wfile.write(resp.content)


def start(port: int = PROXY_PORT):
    server = HTTPServer(('0.0.0.0', port), ProxyHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server