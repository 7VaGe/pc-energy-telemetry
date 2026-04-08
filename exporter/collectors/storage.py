# collectors/storage.py
# Disk I/O telemetry via psutil.disk_io_counters().
# Monitors PhysicalDrive0 (primary) and PhysicalDrive1 (secondary) separately
# using Prometheus labels, computing MB/s as a delta between scrape intervals.

import psutil
import time
from prometheus_client import Gauge

disk_read_mb_s   = Gauge('disk_read_mb_s',      'Disk read throughput in MB/s',  ['disk'])
disk_write_mb_s  = Gauge('disk_write_mb_s',     'Disk write throughput in MB/s', ['disk'])
disk_read_total  = Gauge('disk_read_total_mb',  'Cumulative bytes read (MB)',     ['disk'])
disk_write_total = Gauge('disk_write_total_mb', 'Cumulative bytes written (MB)',  ['disk'])

MONITORED_DISKS = ['PhysicalDrive0', 'PhysicalDrive1']

_prev_counters = None
_prev_time     = None

def collect():
    global _prev_counters, _prev_time

    counters = psutil.disk_io_counters(perdisk=True)
    now      = time.time()

    for disk in MONITORED_DISKS:
        if disk not in counters:
            continue

        c = counters[disk]

        if _prev_counters is not None and disk in _prev_counters:
            delta_t     = now - _prev_time
            delta_read  = c.read_bytes  - _prev_counters[disk].read_bytes
            delta_write = c.write_bytes - _prev_counters[disk].write_bytes

            # Compute instantaneous throughput from counter delta
            disk_read_mb_s.labels(disk=disk).set((delta_read  / delta_t) / 1024 / 1024)
            disk_write_mb_s.labels(disk=disk).set((delta_write / delta_t) / 1024 / 1024)

        # Cumulative totals since system boot
        disk_read_total.labels(disk=disk).set(c.read_bytes  / 1024 / 1024)
        disk_write_total.labels(disk=disk).set(c.write_bytes / 1024 / 1024)

    _prev_counters = counters
    _prev_time     = now