# main.py
# Entry point for the hardware telemetry exporter.

import time
import logging
from prometheus_client import start_http_server, REGISTRY, Gauge
from collectors import gpu, cpu, ram, storage, energy, llm_stats, hardware_profile, llm_proxy, gaming_session
from collectors.llm_discovery import discover_active_llms
import classifier

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
log = logging.getLogger(__name__)

EXPORTER_PORT   = 8000
SCRAPE_INTERVAL = 2
LLM_STATS_INTERVAL = 5  # Fetch API stats every 5 cycles (~10 seconds)

# --- LLM Discovery Prometheus Metrics ---
LLM_ENGINE_INFO = Gauge(
    'llm_engine_info',
    'Active LLM runtime engine (1=running)',
    ['engine', 'model', 'port']
)

LLM_VRAM_BYTES = Gauge(
    'llm_active_model_vram_bytes',
    'VRAM used by the active LLM model in bytes',
    ['engine']
)

def get_metric_value(metric_name: str) -> float:
    for metric in REGISTRY.collect():
        if metric.name == metric_name:
            for sample in metric.samples:
                return sample.value
    return 0.0

def main():
    log.info("Initializing GPU handle via NVML...")
    gpu.init()
    log.info("GPU handle acquired.")

    log.info("Detecting hardware profile and computing baseline power...")
    baseline = hardware_profile.init()
    log.info(f"System baseline power: {baseline:.1f}W")

    log.info(f"Starting LLM proxy on port {llm_proxy.PROXY_PORT}...")
    llm_proxy.start()
    log.info(f"LLM proxy active on http://localhost:{llm_proxy.PROXY_PORT}")

    log.info(f"Starting HTTP server on port {EXPORTER_PORT}...")
    start_http_server(EXPORTER_PORT)
    log.info(f"Exporter running at http://localhost:{EXPORTER_PORT}/metrics")

    log.info("Entering metric collection loop...")

    cycle_counter = 0
    discovered_engines_cache = {}

    while True:
        try:
            # 1 – Hardware metrics (every 2s)
            gpu.collect()
            cpu.collect()
            ram.collect()
            storage.collect()

            # 2 – Classify session (every 2s, fast psutil scan)
            gpu_pct       = get_metric_value('gpu_utilization_percent')
            session, game = classifier.collect(gpu_pct)

            # 3 – Power estimates
            gpu_power_w = get_metric_value('gpu_power_watts_estimated')
            cpu_power_w = get_metric_value('cpu_power_watts_estimated')

            # 4 – Energy and cost
            energy.collect(session=session, gpu_power_w=gpu_power_w, cpu_power_w=cpu_power_w)

            # 5 – Derived values after energy.collect()
            price_eur_kwh = get_metric_value('energy_price_euro_per_kwh')
            total_power_w = get_metric_value('power_total_watts_estimated')

            # 6 – Proxy and gaming session
            llm_proxy.update_power(total_power_w, price_eur_kwh)
            gaming_session.collect(power_w=total_power_w, price_eur_kwh=price_eur_kwh, game=game)

            # 7 – LLM stats probe (legacy, throttled)
            llm_stats.collect(power_w=total_power_w, price_eur_kwh=price_eur_kwh, session=session)

            # 8 – Dynamic LLM Discovery & Stats (Fast scan for processes)
            active_providers = discover_active_llms()
            current_engines = set()

            for provider in active_providers:
                engine = provider.ENGINE_NAME
                current_engines.add(engine)

                # Immediately mark engine as running with last known model (fast, no API call)
                # We update the model name and stats only every N cycles (slow poll)
                if engine not in discovered_engines_cache:
                    log.info(f"New LLM engine detected: {engine}. Forcing stats refresh.")
                    cycle_counter = LLM_STATS_INTERVAL

                # Set process as alive (1)
                LLM_ENGINE_INFO.labels(
                    engine=engine,
                    model=discovered_engines_cache.get(engine, {}).get('model', 'unknown'),
                    port=str(provider.port)
                ).set(1)

            # Remove engines that are no longer running (process died)
            for old_engine in list(discovered_engines_cache.keys()):
                if old_engine not in current_engines:
                    LLM_ENGINE_INFO.remove(old_engine)
                    LLM_VRAM_BYTES.remove(old_engine)
                    log.info(f"LLM Engine '{old_engine}' terminated. Metrics cleared.")
                    del discovered_engines_cache[old_engine]

            # 9 – LLM API Stats Update (Slow poll, every 10s)
            # This queries Ollama / LM Studio APIs for detailed info (model name, vram)
            cycle_counter += 1
            if cycle_counter >= LLM_STATS_INTERVAL:
                cycle_counter = 0
                for provider in active_providers:
                    engine = provider.ENGINE_NAME
                    try:
                        model_name = provider.get_active_model() or "unknown"
                        stats = provider.get_stats()

                        # Update cache
                        discovered_engines_cache[engine] = {'model': model_name}

                        LLM_ENGINE_INFO.labels(
                            engine=engine,
                            model=model_name,
                            port=str(provider.port)
                        ).set(1)

                        vram = stats.get("llm_vram_bytes", 0)
                        LLM_VRAM_BYTES.labels(engine=engine).set(vram)

                    except Exception as e:
                        log.error(f"Error fetching API stats for {engine}: {e}")

            log.info(
                f"session: {session:6s} | gpu: {gpu_pct:.1f}% | "
                f"power: {total_power_w:.1f}W | "
                f"llm_engines: {len(current_engines)} | "
                f"collectors: OK"
            )

        except Exception as e:
            log.error(f"Collection error: {e}")

        time.sleep(SCRAPE_INTERVAL)


if __name__ == '__main__':
    main()