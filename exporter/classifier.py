# classifier.py
# Session classifier: detects current workload type (idle / gaming / llm).
#
# Process name matching is cross-platform:
#   - Names are normalized to lowercase without .exe extension before lookup
#   - GAMING_PROCESSES in collectors/__init__.py stores base names (no extension)
#   - LLM process detection uses both exact names and cmdline keyword scan

import platform
import psutil
from prometheus_client import Gauge, Enum
from collectors import GAMING_PROCESSES, GAMING_GPU_THRESHOLD

session_type = Enum(
    'session_type',
    'Detected workload session type',
    states=['idle', 'gaming', 'llm']
)
session_type_numeric = Gauge(
    'session_type_numeric',
    'Session type as integer (0=idle, 1=gaming, 2=llm)'
)

# LLM runtime process names — stored without .exe for cross-platform matching
_LLM_PROCESSES = {
    'ollama', 'ollama_llama_server', 'llama-server', 'llama-cpp',
    'lm studio', 'lmstudio',
}
_LLM_CMDLINE_KEYWORDS = {'ollama', 'llama', 'llm', 'transformers', 'vllm', 'lmstudio'}
GPU_IDLE_THRESHOLD    = 8.0   # % GPU utilization below which session is idle


def _normalize(name: str) -> str:
    """Lowercase and strip .exe suffix for cross-platform name comparison."""
    return name.lower().removesuffix(".exe")


def _get_active_processes() -> tuple[set[str], list[str]]:
    """Return (normalized_names, cmdlines)."""
    names: set[str]   = set()
    cmdlines: list[str] = []

    for proc in psutil.process_iter(['name', 'cmdline']):
        try:
            raw_name = proc.info['name']
            if raw_name:
                names.add(_normalize(raw_name))
            cmdline = proc.info['cmdline']
            if cmdline:
                cmdlines.append(' '.join(cmdline).lower())
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue

    return names, cmdlines


def collect(gpu_utilization_pct: float) -> tuple[str, str]:
    """
    Classify current session type.
    Returns:
        (session_type, detected_game)
        session_type : 'idle' | 'gaming' | 'llm'
        detected_game: normalized process name of detected game, '' if none
    """
    detected_game = ''

    if gpu_utilization_pct < GPU_IDLE_THRESHOLD:
        result = 'idle'
    else:
        names, cmdlines = _get_active_processes()

        is_llm = (
            bool(_LLM_PROCESSES & names) or
            any(any(kw in c for kw in _LLM_CMDLINE_KEYWORDS) for c in cmdlines)
        )

        if is_llm:
            result = 'llm'
        else:
            # GAMING_PROCESSES contains base names (no .exe) for cross-platform match
            for name in names:
                if name in GAMING_PROCESSES:
                    detected_game = name
                    break
            result = 'gaming' if (detected_game or gpu_utilization_pct >= GAMING_GPU_THRESHOLD) else 'idle'

    session_type.state(result)
    session_type_numeric.set({'idle': 0, 'gaming': 1, 'llm': 2}[result])
    return result, detected_game
