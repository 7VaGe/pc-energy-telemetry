# test_energy_counter.py
# Standalone probe for nvmlDeviceGetTotalEnergyConsumption on RTX 5080 (Blackwell).
#
# Run from the exporter directory:
#   python test_energy_counter.py
#
# EXIT CODES:
#   0 — API supported, prints average power over a 3-second window
#   1 — API not supported on this GPU (NVMLError_NotSupported)
#   2 — NVML init failure or other unexpected error

import sys
import time
import pynvml


def probe_energy_counter(duration_s: float = 3.0, interval_s: float = 0.5) -> None:
    try:
        pynvml.nvmlInit()
    except pynvml.NVMLError as e:
        print(f"[FAIL] NVML init error: {e}")
        sys.exit(2)

    handle = pynvml.nvmlDeviceGetHandleByIndex(0)
    name   = pynvml.nvmlDeviceGetName(handle)
    tdp_w  = pynvml.nvmlDeviceGetPowerManagementLimit(handle) / 1000.0

    print(f"GPU      : {name}")
    print(f"TDP limit: {tdp_w:.1f} W")
    print()

    # --- probe GetTotalEnergyConsumption ---
    try:
        e_start_mj = pynvml.nvmlDeviceGetTotalEnergyConsumption(handle)
    except pynvml.NVMLError_NotSupported:
        print("[RESULT] nvmlDeviceGetTotalEnergyConsumption → NOT SUPPORTED on this GPU.")
        print("         Fallback to TDP*utilization model required.")
        pynvml.nvmlShutdown()
        sys.exit(1)
    except pynvml.NVMLError as e:
        print(f"[FAIL] Unexpected NVML error: {e}")
        pynvml.nvmlShutdown()
        sys.exit(2)

    print("[OK] nvmlDeviceGetTotalEnergyConsumption is supported.")
    print(f"     Sampling for {duration_s:.0f}s (interval {interval_s:.1f}s) ...\n")

    samples = []
    t_prev  = time.perf_counter()
    e_prev  = e_start_mj

    for _ in range(int(duration_s / interval_s)):
        time.sleep(interval_s)

        t_now = time.perf_counter()
        e_now = pynvml.nvmlDeviceGetTotalEnergyConsumption(handle)

        delta_mj = e_now - e_prev
        delta_s  = t_now - t_prev
        power_w  = (delta_mj / 1000.0) / delta_s   # mJ → J → W

        util = pynvml.nvmlDeviceGetUtilizationRates(handle).gpu
        print(f"  t={t_now - (t_prev - interval_s):.1f}s | "
              f"energy_delta={delta_mj:.1f} mJ | "
              f"avg_power={power_w:.1f} W | "
              f"gpu_util={util}%")

        samples.append(power_w)
        t_prev = t_now
        e_prev = e_now

    avg_w = sum(samples) / len(samples)
    print()
    print(f"[RESULT] Average GPU power over {duration_s:.0f}s: {avg_w:.1f} W")
    print(f"         TDP*util estimate would give: "
          f"{tdp_w * pynvml.nvmlDeviceGetUtilizationRates(handle).gpu / 100:.1f} W")

    pynvml.nvmlShutdown()
    sys.exit(0)


if __name__ == "__main__":
    probe_energy_counter()
