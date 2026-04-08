import psutil
from prometheus_client import Gauge

ram_used        = Gauge('ram_used_mb',        'RAM utilizzata in MB')
ram_total       = Gauge('ram_total_mb',       'RAM totale in MB')
ram_available   = Gauge('ram_available_mb',   'RAM disponibile in MB')
ram_percent     = Gauge('ram_percent',        'Percentuale RAM utilizzata')

def collect():
    mem = psutil.virtual_memory()
    ram_used.set(mem.used      / 1024 / 1024)
    ram_total.set(mem.total    / 1024 / 1024)
    ram_available.set(mem.available / 1024 / 1024)
    ram_percent.set(mem.percent)