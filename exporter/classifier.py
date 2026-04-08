import psutil
from prometheus_client import Gauge, Enum

session_type = Enum(
    'session_type',
    'Tipo di sessione rilevata',
    states=['idle', 'gaming', 'llm']
)
session_type_numeric = Gauge(
    'session_type_numeric',
    'Tipo sessione come numero (0=idle, 1=gaming, 2=llm)'
)

GAMING_PROCESSES = {
    'league of legends.exe',
    'leagueclient.exe',
    'witcher3.exe',
    'cyberpunk2077.exe',
    'cs2.exe',
    'valorant.exe',
    'fortnite.exe',
    'eldenring.exe',
    'steam.exe',
}

LLM_PROCESSES = {
    'ollama.exe',
    'ollama_llama_server.exe',
    'llama-server.exe',
    'llama-cpp.exe',
}

LLM_PROCESSES_UI = {
    'lm studio.exe',   # rilevato solo se GPU attiva
}

LLM_CMDLINE_KEYWORDS = {
    'ollama',
    'llama',
    'llm',
    'transformers',
    'vllm',
    'inference',
    'lmstudio',
}

# Soglie utilizzo GPU
GPU_GAMING_THRESHOLD     = 30.0
GPU_LLM_THRESHOLD        = 10.0
GPU_LLM_UI_THRESHOLD     = 10.0  # soglia per LM Studio UI (Electron idle usa poca GPU)

def _get_active_processes():
    names    = set()
    cmdlines = []
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

def classify(gpu_utilization_pct: float) -> str:
    names, cmdlines = _get_active_processes()

    # Priorità 1: processo LLM dedicato (sempre LLM indipendente da GPU)
    for proc_name in LLM_PROCESSES:
        if proc_name in names:
            return 'llm'

    # Priorità 2: Python con keyword LLM in cmdline
    if 'python.exe' in names:
        for cmdline in cmdlines:
            if any(kw in cmdline for kw in LLM_CMDLINE_KEYWORDS):
                return 'llm'

    # Priorità 3: LM Studio UI attiva + GPU sopra soglia = inferenza in corso
    if 'lm studio.exe' in names and gpu_utilization_pct >= GPU_LLM_UI_THRESHOLD:
        return 'llm'

    # Priorità 4: processo gaming esplicito
    for proc_name in GAMING_PROCESSES:
        if proc_name in names:
            return 'gaming'

    # Priorità 5: fallback su utilizzo GPU
    if gpu_utilization_pct >= GPU_GAMING_THRESHOLD:
        return 'gaming'

    return 'idle'

SESSION_TYPE_MAP = {'idle': 0, 'gaming': 1, 'llm': 2}

def collect(gpu_utilization_pct: float) -> str:
    result = classify(gpu_utilization_pct)
    session_type.state(result)
    session_type_numeric.set(SESSION_TYPE_MAP[result])
    return result