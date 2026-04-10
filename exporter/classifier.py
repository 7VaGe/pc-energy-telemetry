# classifier.py
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

LLM_PROCESSES        = {'ollama.exe', 'ollama_llama_server.exe', 'llama-server.exe', 'llama-cpp.exe'}
LLM_PROCESSES_UI     = {'lm studio.exe'}
LLM_CMDLINE_KEYWORDS = {'ollama', 'llama', 'llm', 'transformers', 'vllm'}
GPU_IDLE_THRESHOLD   = 8.0


def _get_active_processes():
    names, cmdlines = set(), []
    for proc in psutil.process_iter(['name', 'cmdline']):
        try:
            name = proc.info['name']
            if name:
                names.add(name.lower())
            cmdline = proc.info['cmdline']
            if cmdline:
                cmdlines.append(' '.join(cmdline).lower())
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return names, cmdlines


def collect(gpu_utilization_pct: float) -> tuple[str, str]:
    """
    Classifica la sessione corrente.
    Returns:
        (session_type, detected_game)
        session_type: 'idle' | 'gaming' | 'llm'
        detected_game: nome del processo gioco rilevato, '' se nessuno
    """
    detected_game = ''

    if gpu_utilization_pct < GPU_IDLE_THRESHOLD:
        result = 'idle'
    else:
        names, cmdlines = _get_active_processes()

        is_llm = (any(p in names for p in LLM_PROCESSES) or
                  any(p in names for p in LLM_PROCESSES_UI) or
                  any(any(kw in c for kw in LLM_CMDLINE_KEYWORDS) for c in cmdlines))

        if is_llm:
            result = 'llm'
        else:
            for name in names:
                if name in GAMING_PROCESSES:
                    detected_game = name
                    break
            result = 'gaming' if (detected_game or gpu_utilization_pct >= GAMING_GPU_THRESHOLD) else 'idle'

    session_type.state(result)
    session_type_numeric.set({'idle': 0, 'gaming': 1, 'llm': 2}[result])
    return result, detected_game