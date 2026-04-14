# collectors/__init__.py
# Shared constants used across collectors.
#
# GAMING_PROCESSES: cross-platform process name set.
# Process names are stored WITHOUT the .exe extension so they match
# on both Windows (where psutil strips nothing) and Linux/macOS.
# The classifier normalizes names before lookup — see classifier.py.

import platform as _platform

# ---- Cross-platform game process names (no extension) ----
# Add new titles here without .exe — the classifier handles both forms.
_GAMING_PROCESSES_BASE = {
    # MOBA
    "league of legends",
    "leagueclient",
    # FPS
    "cs2",
    "valorant",
    "fortnite",
    "overwatch",
    "r5apex",              # Apex Legends
    "cod",                 # Call of Duty (various)
    "battlefront",
    # RPG / Open World
    "witcher3",
    "cyberpunk2077",
    "eldenring",
    "hogwartslegacy",
    "crimsondesert",
    "rdr2",
    # Strategy
    "totalwar",
    "age of empires",
    # Racing
    "forzamotorsport",
    "forzahorizon5",
    "forzahorizon4",
    # Other
    "baldursgate3",
    "pathoftitans",
    "starfield",
    "diablo iv",
    "steam",               # Steam itself signals gaming intent
}

# Platform-specific: add .exe variants on Windows for exact matching
if _platform.system() == "Windows":
    GAMING_PROCESSES = _GAMING_PROCESSES_BASE | {
        name + ".exe" for name in _GAMING_PROCESSES_BASE
    }
else:
    GAMING_PROCESSES = _GAMING_PROCESSES_BASE

GAMING_GPU_THRESHOLD = 30.0  # % GPU utilization above which session = gaming
