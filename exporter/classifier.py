# classifier.py
# Workload session classifier.
# Determines whether the system is running a gaming session, an LLM inference
# session, or is idle, based on active process names and GPU utilization.
#
# Classification priority (highest to lowest):
#   1. Known LLM backend process present           -> llm
#   2. Python process with LLM-related cmdline     -> llm
#   3. LM Studio UI open + GPU above threshold     -> llm
#   4. Known gaming process present                -> gaming
#   5. GPU utilization above gaming threshold      -> gaming
#   6. Default                                     -> idle

import psutil
from prometheus_client import Gauge, Enum

session_type = Enum(
    'session_type',
    'Detected workload session type',
    states=['idle', 'gaming', 'llm']
)
session_type_numeric = Gauge(
    'session_type_numeric',
    'Session type as integer (0=idle, 1=gaming, 2=llm)'
)

# Process name lists — lowercase, matched against psutil process names
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

# Dedicated LLM backend processes (always classified as llm regardless of GPU load)
LLM_PROCESSES = {
    'ollama.exe',
    'ollama_llama_server.exe',
    'llama-server.exe',
    'llama-cpp.exe',
}

# UI-based LLM tools — classified as llm only when GPU load exceeds threshold
LLM_PROCESSES_UI = {
    'lm studio.exe',
}

LLM_CMDLINE_KEYWORDS = {
    'ollama', 'llama', 'llm',
    'transformers', 'vllm',
    'inference', 'lmstudio',
}

# GPU utilization thresholds (percent)
GPU_GAMING_THRESHOLD = 30.0
GPU_LLM_UI_THRESHOLD = 10.0  # Minimum GPU load to confirm LM Studio is inferring

def _get_active_processes():
    # Returns a set of lowercase process names and a list of joined cmdline strings.
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

    # Priority 1: dedicated LLM backend
    for proc_name in LLM_PROCESSES:
        if proc_name in names:
            return 'llm'

    # Priority 2: Python interpreter running LLM workload
    if 'python.exe' in names:
        for cmdline in cmdlines:
            if any(kw in cmdline for kw in LLM_CMDLINE_KEYWORDS):
                return 'llm'

    # Priority 3: LM Studio UI active and GPU confirms inference is running
    if 'lm studio.exe' in names and gpu_utilization_pct >= GPU_LLM_UI_THRESHOLD:
        return 'llm'

    # Priority 4: known gaming process
    for proc_name in GAMING_PROCESSES:
        if proc_name in names:
            return 'gaming'

    # Priority 5: high GPU load without a known process -> assume gaming
    if gpu_utilization_pct >= GPU_GAMING_THRESHOLD:
        return 'gaming'

    return 'idle'

SESSION_TYPE_MAP = {'idle': 0, 'gaming': 1, 'llm': 2}

def collect(gpu_utilization_pct: float) -> str:
    result = classify(gpu_utilization_pct)
    session_type.state(result)
    session_type_numeric.set(SESSION_TYPE_MAP[result])
    return result