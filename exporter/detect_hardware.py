# detect_hardware.py
# Hardware detection script for baseline power estimation.
# Run this script once to identify system components.
# Output is used to configure hardware_profile.py accurately.
#
# Usage: python detect_hardware.py

import psutil
import platform
import subprocess
import json

def run_powershell(cmd: str) -> str:
    result = subprocess.run(
        ['powershell', '-Command', cmd],
        capture_output=True, text=True
    )
    return result.stdout.strip()

def detect_cpu():
    name = run_powershell("(Get-WmiObject Win32_Processor).Name")
    cores = psutil.cpu_count(logical=False)
    threads = psutil.cpu_count(logical=True)
    freq = psutil.cpu_freq()
    print(f"\n[CPU]")
    print(f"  Nome:    {name}")
    print(f"  Core:    {cores} fisici / {threads} logici")
    print(f"  Freq:    {freq.max:.0f} MHz max")

def detect_ram():
    sticks = run_powershell(
        "Get-WmiObject Win32_PhysicalMemory | Select-Object Manufacturer, PartNumber, Capacity, Speed, MemoryType | ConvertTo-Json"
    )
    mem = psutil.virtual_memory()
    print(f"\n[RAM]")
    print(f"  Totale:  {mem.total / 1024**3:.1f} GB")
    try:
        data = json.loads(sticks)
        if isinstance(data, dict):
            data = [data]
        for i, stick in enumerate(data):
            cap = int(stick.get('Capacity', 0)) / 1024**3
            speed = stick.get('Speed', 'N/A')
            part = stick.get('PartNumber', 'N/A').strip()
            mfr = stick.get('Manufacturer', 'N/A').strip()
            print(f"  Stick {i+1}: {cap:.0f}GB | {speed} MHz | {mfr} {part}")
    except Exception as e:
        print(f"  (dettaglio non disponibile: {e})")

def detect_storage():
    disks = run_powershell(
        "Get-WmiObject Win32_DiskDrive | Select-Object Model, Size, InterfaceType, MediaType | ConvertTo-Json"
    )
    print(f"\n[STORAGE]")
    try:
        data = json.loads(disks)
        if isinstance(data, dict):
            data = [data]
        for i, disk in enumerate(data):
            size = int(disk.get('Size', 0)) / 1024**3
            model = disk.get('Model', 'N/A').strip()
            iface = disk.get('InterfaceType', 'N/A')
            media = disk.get('MediaType', 'N/A')
            print(f"  Disco {i+1}: {model} | {size:.0f} GB | {iface} | {media}")
    except Exception as e:
        print(f"  (dettaglio non disponibile: {e})")

def detect_gpu():
    gpu = run_powershell(
        "Get-WmiObject Win32_VideoController | Select-Object Name, AdapterRAM | ConvertTo-Json"
    )
    print(f"\n[GPU]")
    try:
        data = json.loads(gpu)
        if isinstance(data, dict):
            data = [data]
        for i, g in enumerate(data):
            name = g.get('Name', 'N/A')
            vram = int(g.get('AdapterRAM', 0)) / 1024**3
            print(f"  GPU {i+1}: {name} | VRAM: {vram:.0f} GB")
    except Exception as e:
        print(f"  (dettaglio non disponibile: {e})")

def detect_motherboard():
    board = run_powershell(
        "Get-WmiObject Win32_BaseBoard | Select-Object Manufacturer, Product | ConvertTo-Json"
    )
    print(f"\n[MOTHERBOARD]")
    try:
        data = json.loads(board)
        mfr = data.get('Manufacturer', 'N/A').strip()
        product = data.get('Product', 'N/A').strip()
        print(f"  Modello: {mfr} {product}")
    except Exception as e:
        print(f"  (dettaglio non disponibile: {e})")

def detect_psu():
    # PSU non è rilevabile via software su Windows
    # Chiediamo all'utente
    print(f"\n[PSU]")
    print(f"  Non rilevabile via software.")
    print(f"  Inserisci manualmente: wattaggio e certificazione (es. 1000W 80+ Gold)")

def detect_cooling():
    # Cooling non rilevabile direttamente
    fans = run_powershell(
        "Get-WmiObject Win32_Fan | Select-Object Name, DesiredSpeed | ConvertTo-Json"
    )
    print(f"\n[COOLING]")
    try:
        data = json.loads(fans)
        if isinstance(data, dict):
            data = [data]
        for f in data:
            print(f"  Ventola: {f.get('Name', 'N/A')}")
    except:
        print(f"  Ventole non rilevate via WMI (normale su Windows).")
        print(f"  Inserisci manualmente: tipo cooler (AIO 360mm / Air / AIO 240mm)")

def detect_os():
    print(f"\n[SISTEMA OPERATIVO]")
    print(f"  {platform.system()} {platform.release()} {platform.version()}")
    print(f"  Python: {platform.python_version()}")

if __name__ == '__main__':
    print("=" * 60)
    print("  Hardware Detection Script — Telemetria Energetica PC")
    print("=" * 60)
    detect_os()
    detect_cpu()
    detect_ram()
    detect_storage()
    detect_gpu()
    detect_motherboard()
    detect_psu()
    detect_cooling()
    print("\n" + "=" * 60)
    print("  Copia questo output e condividilo per configurare")
    print("  hardware_profile.py con valori precisi.")
    print("=" * 60)