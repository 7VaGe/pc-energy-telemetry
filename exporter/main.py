# main.py
# Entry point for the hardware telemetry exporter.
# Initializes collectors, starts the Prometheus HTTP server,
# and runs the metric collection loop at a fixed scrape interval.

import time
import logging
from prometheus_client import start_http_server, REGISTRY
from collectors import gpu, cpu, ram, storage, energy, llm_stats, hardware_profile
import classifier

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
log = logging.getLogger(__name__)

EXPORTER_PORT   = 8000
SCRAPE_INTERVAL = 2

def get_metric_value(metric_name: str) -> float:
    # Read current value of a named gauge from the Prometheus registry.
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

    log.info(f"Starting HTTP server on port {EXPORTER_PORT}...")
    start_http_server(EXPORTER_PORT)
    log.info(f"Exporter running at http://localhost:{EXPORTER_PORT}/metrics")

    log.info("Entering metric collection loop...")
    while True:
        try:
            gpu.collect()
            cpu.collect()
            ram.collect()
            storage.collect()

            gpu_pct     = get_metric_value('gpu_utilization_percent')
            session     = classifier.collect(gpu_pct)

            gpu_power_w = get_metric_value('gpu_power_watts_estimated')
            cpu_power_w = get_metric_value('cpu_power_watts_estimated')

            energy.collect(
                session     = session,
                gpu_power_w = gpu_power_w,
                cpu_power_w = cpu_power_w,
            )

            price_eur_kwh = get_metric_value('energy_price_euro_per_kwh')
            total_power_w = get_metric_value('power_total_watts_estimated')

            llm_stats.collect(
                power_w       = total_power_w,
                price_eur_kwh = price_eur_kwh,
                session       = session,
            )

            log.info(
                f"session: {session:6s} | "
                f"gpu: {gpu_pct:.1f}% | "
                f"power: {total_power_w:.1f}W | "
                f"tariff: F{int(get_metric_value('energy_tariff_active'))} | "
                f"collectors: OK"
            )

        except Exception as e:
            log.error(f"Collection error: {e}")

        time.sleep(SCRAPE_INTERVAL)

if __name__ == '__main__':
    main()