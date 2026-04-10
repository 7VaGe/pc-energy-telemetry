# collectors/llm_proxy.py
# Proxy HTTP che intercetta le richieste LM Studio per misurare energia e costo.
#
# Thread safety:
#   Il proxy gira in un thread separato. Il _lock protegge TUTTE le variabili
#   di sessione Python. Le operazioni Prometheus sono thread-safe e si eseguono
#   fuori dal lock.

import threading
import time
import json
import requests
from http.server import HTTPServer, BaseHTTPRequestHandler
from prometheus_client import Counter, Gauge

LM_STUDIO_URL        = 'http://localhost:1234'
PROXY_PORT           = 1235
SESSION_IDLE_TIMEOUT = 300

llm_request_total         = Counter('llm_request_total',               'Total LLM requests intercepted')
llm_request_tokens_total  = Counter('llm_request_tokens_total',        'Total completion tokens')
llm_request_prompt_tokens = Counter('llm_request_prompt_tokens_total', 'Total prompt tokens')
llm_request_cost_euro     = Counter('llm_request_cost_euro_total',     'Total LLM energy cost (EUR)')

llm_session_active        = Gauge('llm_session_active',           'LLM session active (1=yes)')
llm_session_duration      = Gauge('llm_session_duration_s',       'Current LLM session duration (s)')
llm_session_tokens_total  = Gauge('llm_session_tokens_total',     'Total tokens in current session')
llm_session_tokens        = Gauge('llm_session_tokens',           'Tokens generated in current session')
llm_session_requests      = Gauge('llm_session_requests',         'Requests in current session')
llm_session_cost          = Gauge('llm_session_cost_euro',        'Cost of current session (EUR)')
llm_last_tokens           = Gauge('llm_last_request_tokens',      'Tokens in last request')
llm_last_tps              = Gauge('llm_last_request_tps',         'Tokens/s in last request')
llm_last_latency          = Gauge('llm_last_request_latency_s',   'Latency of last request (s)')
llm_last_request_cost     = Gauge('llm_last_request_cost_euro',   'Cost of last request (EUR)')
llm_total_historical_cost = Counter('llm_total_energy_cost_euro', 'Total historical LLM energy cost (EUR)')

# Lock unico â€” protegge TUTTE le variabili di stato condivise
_lock = threading.Lock()

_power_w            = 0.0
_price_eur_kwh      = 0.28
_session_active     = False
_session_start_time = 0.0
_session_requests   = 0
_session_tokens     = 0
_session_cost       = 0.0
_session_timer      = None


def update_power(power_w: float, price_eur_kwh: float):
    global _power_w, _price_eur_kwh
    with _lock:
        _power_w       = power_w
        _price_eur_kwh = price_eur_kwh


def _close_session():
    global _session_active
    with _lock:
        if not _session_active:
            return
        _session_active = False
        cost = _session_cost
    llm_total_historical_cost.inc(cost)
    llm_session_active.set(0)


def _schedule_session_timeout():
    global _session_timer
    with _lock:
        if _session_timer is not None:
            _session_timer.cancel()
        timer = threading.Timer(SESSION_IDLE_TIMEOUT, _close_session)
        timer.daemon = True
        _session_timer = timer
    timer.start()


def _record_request(completion_tokens: int, prompt_tokens: int,
                    tps: float, latency_s: float, generation_time_s: float):
    global _session_requests, _session_tokens, _session_cost
    global _session_active, _session_start_time

    with _lock:
        current_power = _power_w
        current_price = _price_eur_kwh

    energy_kwh = (current_power * generation_time_s) / 3600.0 / 1000.0
    cost_euro  = energy_kwh * current_price

    llm_last_tokens.set(completion_tokens)
    llm_last_tps.set(tps)
    llm_last_latency.set(latency_s)
    llm_last_request_cost.set(cost_euro)
    llm_request_total.inc()
    llm_request_tokens_total.inc(completion_tokens)
    llm_request_prompt_tokens.inc(prompt_tokens)
    llm_request_cost_euro.inc(cost_euro)

    newly_started = False
    with _lock:
        if not _session_active:
            _session_active     = True
            _session_start_time = time.time()
            _session_requests   = 0
            _session_tokens     = 0
            _session_cost       = 0.0
            newly_started       = True
        _session_requests += 1
        _session_tokens   += completion_tokens
        _session_cost     += cost_euro
        snap_tokens    = _session_tokens
        snap_requests  = _session_requests

    if newly_started:
        llm_session_cost.set(0)
        llm_session_duration.set(0)
        llm_session_tokens_total.set(0)
        llm_session_active.set(1)

    llm_session_tokens.set(snap_tokens)
    llm_session_requests.set(snap_requests)
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
                data        = json.loads(resp_body)
                usage       = data.get('usage', {})
                stats_block = data.get('stats', {})
                c_tok = usage.get('completion_tokens', 0)
                p_tok = usage.get('prompt_tokens', 0)
                gen_t = stats_block.get('generation_time', 0.0) or latency
                tps   = stats_block.get('tokens_per_second', 0.0)
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
        self.send_header('Content-Type', resp.headers.get('Content-Type', 'application/json'))
        self.end_headers()
        self.wfile.write(resp.content)


def start(port: int = PROXY_PORT):
    server = HTTPServer(('0.0.0.0', port), ProxyHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server
