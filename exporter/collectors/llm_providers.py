# exporter/collectors/llm_providers.py

import logging
import requests
from abc import ABC, abstractmethod
from typing import Dict, List, Optional

log = logging.getLogger(__name__)

class BaseLLMProvider(ABC):
    """Abstract base class for all LLM runtime providers."""

    # These must be defined in child classes
    ENGINE_NAME: str = ""
    PROCESS_NAMES: List[str] = []
    ARGS_HINTS: List[str] = []
    ARGS_EXCLUDE: List[str] = []
    DEFAULT_PORTS: List[int] = []

    def __init__(self, pid: int, port: int, cmdline: List[str]):
        self.pid = pid
        self.port = port
        self.cmdline = cmdline

    @abstractmethod
    def get_active_model(self) -> Optional[str]:
        """Returns the name of the currently loaded model, if detectable via API."""
        pass

    @abstractmethod
    def get_stats(self) -> Dict:
        """Returns runtime-specific statistics (tokens/s, queue size, VRAM used)."""
        pass

# --- CONCRETE PROVIDERS ---

class OllamaProvider(BaseLLMProvider):
    ENGINE_NAME = "ollama"
    PROCESS_NAMES = ["ollama.exe", "ollama"]
    ARGS_HINTS = []
    ARGS_EXCLUDE = ["run"] # Exclude CLI client processes
    DEFAULT_PORTS = [11434]

    def get_active_model(self) -> Optional[str]:
        try:
            # /api/ps returns only models currently loaded in VRAM
            res = requests.get(f"http://localhost:{self.port}/api/ps", timeout=2)
            if res.ok:
                data = res.json()
                if data.get("models"):
                    return data["models"][0].get("name")

                # If VRAM is empty, check if models are at least installed locally
                res_tags = requests.get(f"http://localhost:{self.port}/api/tags", timeout=2)
                if res_tags.ok and res_tags.json().get("models"):
                    return "Idle (Model in disk, not in VRAM)"

                return "Idle (No models installed)"

        except requests.RequestException as e:
            log.warning(f"Ollama API request failed: {e}")
        return None

    def get_stats(self) -> Dict:
        try:
            res = requests.get(f"http://localhost:{self.port}/api/ps", timeout=2)
            if res.ok:
                data = res.json().get("models", [])
                if data:
                    model = data[0]
                    return {
                        "llm_vram_bytes": model.get("size", 0),
                        "llm_model_format": model.get("details", {}).get("format", "unknown")
                    }
                return {"llm_vram_bytes": 0} # VRAM empty
        except requests.RequestException:
            pass
        return {}

class LMStudioProvider(BaseLLMProvider):
    ENGINE_NAME = "lm_studio"
    PROCESS_NAMES = ["lm studio.exe"]
    ARGS_HINTS = []
    ARGS_EXCLUDE = ["--type="] # Ignore Electron child processes
    DEFAULT_PORTS = [1234]

    def get_active_model(self) -> Optional[str]:
        try:
            res = requests.get(f"http://localhost:{self.port}/v1/models", timeout=2)
            if res.ok:
                data = res.json()
                if data.get("data"):
                    return data["data"][0].get("id")
        except requests.RequestException:
            pass
        return None

    def get_stats(self) -> Dict:
        # LM Studio doesn't have a native stats API, relies on proxy intercept for tokens/s
        return {"llm_engine": "lmstudio"}

class LlamaCppProvider(BaseLLMProvider):
    ENGINE_NAME = "llama_cpp"
    PROCESS_NAMES = ["llama-server.exe", "main.exe", "llama-cli.exe"]
    ARGS_HINTS = ["--model", "--port"]
    ARGS_EXCLUDE = []
    DEFAULT_PORTS = [8080]

    def get_active_model(self) -> Optional[str]:
        # llama.cpp doesn't expose model name easily via API
        return "llama_cpp_model"

    def get_stats(self) -> Dict:
        try:
            res = requests.get(f"http://localhost:{self.port}/health", timeout=2)
            if res.ok:
                status = res.json().get("status")
                return {"llm_server_status": 1 if status == "ok" else 0}
        except requests.RequestException:
            pass
        return {}

class PythonRuntimeProvider(BaseLLMProvider):
    ENGINE_NAME = "python_runtime"
    PROCESS_NAMES = ["python.exe", "python3", "python"]
    ARGS_HINTS = ["vllm", "transformers", "oobabooga", "exui"]
    ARGS_EXCLUDE = []
    DEFAULT_PORTS = [5000, 8000, 8080]

    def get_active_model(self) -> Optional[str]:
        # Hard to detect without specific API endpoints
        return None

    def get_stats(self) -> Dict:
        # Relies entirely on hardware metrics (GPU/VRAM)
        return {"llm_engine": "python_runtime"}