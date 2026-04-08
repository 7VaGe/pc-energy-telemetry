# main.py
# Entry point for the hardware telemetry exporter.
# Initializes collectors, starts the Prometheus HTTP server,
# and runs the metric collection loop at a fixed scrape interval.

import time
import logging
from prometheus_client import start_http_server, REGISTRY
from collectors import gpu, cpu, ram, storage
import classifier

# Configure structured logging with timestamps
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
log = logging.getLogger(__name__)

# Exporter configuration
EXPORTER_PORT   = 8000   # Port exposed to Prometheus scraper
SCRAPE_INTERVAL = 2      # Collection frequency in seconds

def get_gpu_utilization() -> float:
    # Read the current GPU utilization from the Prometheus registry.
    # Used as input signal for session classification.
    for metric in REGISTRY.collect():
        if metric.name == 'gpu_utilization_percent':
            for sample in metric.samples:
                return sample.value
    return 0.0

def main():
    # Initialize NVML handle before entering the collection loop
    log.info("Initializing GPU handle via NVML...")
    gpu.init()
    log.info("GPU handle acquired.")

    # Start the HTTP server that exposes /metrics to Prometheus
    log.info(f"Starting HTTP server on port {EXPORTER_PORT}...")
    start_http_server(EXPORTER_PORT)
    log.info(f"Exporter running at http://localhost:{EXPORTER_PORT}/metrics")

    log.info("Entering metric collection loop...")
    while True:
        try:
            # Collect hardware metrics from each subsystem
            gpu.collect()
            cpu.collect()
            ram.collect()
            storage.collect()

            # Classify current workload based on active processes and GPU load
            gpu_pct = get_gpu_utilization()
            session = classifier.collect(gpu_pct)

            log.info(
                f"session: {session:6s} | "
                f"gpu_util: {gpu_pct:.1f}% | "
                f"collectors: OK"
            )

        except Exception as e:
            log.error(f"Collection error: {e}")

        time.sleep(SCRAPE_INTERVAL)

if __name__ == '__main__':
    main()