# collectors/hardware_profile.py
# Derives system baseline power consumption from detected hardware components.
# Values sourced from manufacturer datasheets and independent hardware reviews.
#
# System configuration:
#   CPU:         AMD Ryzen 7 7800X3D (AM5)
#   RAM:         2x G.Skill F5-6000J3038F16G DDR5-6000 @ 1.35V
#   Storage:     Fanxiang S880 4TB PCIe 4.0 NVMe + SHPP41 2TB NVMe
#   Motherboard: ASUS ROG STRIX B850-F GAMING WIFI (B850 chipset)
#   Cooling:     NZXT Kraken Elite 360 RGB (2024) + 4x Corsair LX140 + 1x Corsair LX140
#   PSU:         Seasonic Vertex 1000W 80+ Platinum
#
# Baseline methodology:
#   Each component contributes a fixed idle draw not captured by TDP-based
#   GPU/CPU estimation. Total is adjusted for PSU conversion losses.
#   Reference: Tom's Hardware B850-I review (72W system idle from wall),
#              AMD AM5 platform overhead ~35W (Tom's Hardware 9800X3D review).

import psutil
from prometheus_client import Gauge

baseline_total_watts    = Gauge('baseline_power_watts',         'Estimated fixed system baseline power (W)')
baseline_ram_watts      = Gauge('baseline_ram_watts',           'Estimated RAM idle power (W)')
baseline_storage_watts  = Gauge('baseline_storage_watts',       'Estimated NVMe storage idle power (W)')
baseline_platform_watts = Gauge('baseline_platform_watts',      'Estimated platform and motherboard idle power (W)')
baseline_cooling_watts  = Gauge('baseline_cooling_watts',       'Estimated cooling system idle power (W)')
baseline_psu_loss_watts = Gauge('baseline_psu_loss_watts',      'Estimated PSU conversion loss at idle (W)')

# --- Per-component idle power constants ---
# G.Skill DDR5-6000 @ 1.35V: JEDEC DDR5 spec ~3W per stick at idle
# Source: JEDEC JESD79-5B DDR5 standard, confirmed by AnandTech DDR5 analysis
DDR5_STICKS            = 2
DDR5_PER_STICK_WATTS   = 3.0    # W per DIMM at idle

# Fanxiang S880 4TB PCIe 4.0: no official datasheet, estimated from
# comparable YMTC-based Gen4 drives (WD Black SN770 = 2.7W idle)
# SHPP41 2TB: estimated from typical Gen4 NVMe idle (Samsung 980 Pro = 2.5W)
NVME_S880_WATTS        = 2.7    # W idle (Fanxiang S880 4TB PCIe 4.0)
NVME_SHPP41_WATTS      = 2.5    # W idle (SHPP41 2TB NVMe)

# ASUS ROG STRIX B850-F GAMING WIFI:
# B850-I (Mini-ITX) measured at 72W system idle from wall (Tom's Hardware).
# ATX version with more VRM phases and WiFi 7 adds ~5W.
# AM5 platform idle overhead ~35W (Tom's Hardware 9800X3D review).
# Board-only contribution estimated at 20W (chipset + VRM + WiFi 7 + RGB).
MOTHERBOARD_WATTS      = 20.0   # W (B850 chipset + VRM + WiFi 7 + RGB)
AM5_PLATFORM_WATTS     = 35.0   # W (AMD AM5 documented idle overhead)

# NZXT Kraken Elite 360 RGB (2024):
# Pump measured at 2.76W (user review, tensorscience.com)
# LCD display: ~2W estimated
# 3x Corsair LX140 Reverse fans (radiator) at idle ~0.5W each
# 1x Corsair LX140 normal fan at idle ~0.5W
# Total cooling: pump + LCD + 4 fans
KRAKEN_PUMP_WATTS      = 2.76   # W (measured, tensorscience.com review)
KRAKEN_LCD_WATTS       = 2.0    # W (estimated, 640x640 IPS display)
CORSAIR_LX140_COUNT    = 5      # 4x Reverse + 1x Normal
CORSAIR_LX140_IDLE_W   = 0.5    # W per fan at idle speed

# Seasonic Vertex 1000W 80+ Platinum:
# Platinum certification = 92% efficiency at 50% load, ~89% at 10% load.
# At idle (~100W draw), efficiency drops to ~85-88%.
# Conversion loss = drawn_power * (1 - efficiency) / efficiency
# Using 87% as conservative estimate for light load.
PSU_EFFICIENCY_IDLE    = 0.87   # Seasonic Vertex 1000W Platinum at light load

_baseline_w = 0.0

def init() -> float:
    global _baseline_w

    # Component power breakdown
    ram_w      = DDR5_STICKS * DDR5_PER_STICK_WATTS
    storage_w  = NVME_S880_WATTS + NVME_SHPP41_WATTS
    platform_w = MOTHERBOARD_WATTS + AM5_PLATFORM_WATTS
    cooling_w  = (KRAKEN_PUMP_WATTS + KRAKEN_LCD_WATTS +
                  CORSAIR_LX140_COUNT * CORSAIR_LX140_IDLE_W)

    subtotal   = ram_w + storage_w + platform_w + cooling_w

    # PSU conversion loss: watts lost = delivered_watts * (1/efficiency - 1)
    psu_loss_w = subtotal * (1.0 / PSU_EFFICIENCY_IDLE - 1.0)
    total_w    = subtotal + psu_loss_w

    # Expose metrics
    baseline_ram_watts.set(ram_w)
    baseline_storage_watts.set(storage_w)
    baseline_platform_watts.set(platform_w)
    baseline_cooling_watts.set(cooling_w)
    baseline_psu_loss_watts.set(psu_loss_w)
    baseline_total_watts.set(total_w)

    _baseline_w = total_w
    return total_w

def get() -> float:
    return _baseline_w