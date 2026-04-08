# collectors/ram.py
# System RAM telemetry via psutil.virtual_memory().
# Reports aggregate figures across all installed DIMM slots.

import psutil
from prometheus_client import Gauge

ram_used      = Gauge('ram_used_mb',      'RAM currently in use (MB)')
ram_total     = Gauge('ram_total_mb',     'Total installed RAM (MB)')
ram_available = Gauge('ram_available_mb', 'RAM available without swapping (MB)')
ram_percent   = Gauge('ram_percent',      'RAM utilization in percent')

def collect():
    mem = psutil.virtual_memory()
    ram_used.set(mem.used       / 1024 / 1024)
    ram_total.set(mem.total     / 1024 / 1024)
    ram_available.set(mem.available / 1024 / 1024)
    ram_percent.set(mem.percent)