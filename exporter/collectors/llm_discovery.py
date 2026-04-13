# exporter/collectors/llm_discovery.py

import logging
import re
import inspect
import psutil
from typing import List, Dict, Optional, Set
from .llm_providers import BaseLLMProvider

log = logging.getLogger(__name__)

def _get_providers() -> List[BaseLLMProvider]:
    """Dynamically finds all BaseLLMProvider subclasses."""
    providers = []
    # Import the module relatively to ensure classes are loaded
    from . import llm_providers as prov_module
    for name, obj in inspect.getmembers(prov_module):
        if inspect.isclass(obj) and issubclass(obj, BaseLLMProvider) and obj is not BaseLLMProvider:
            providers.append(obj)
    return providers

def discover_active_llms() -> List[BaseLLMProvider]:
    """
    Scans running processes and maps them to LLMProvider instances.
    """
    active_runtimes = []
    seen_pids = set()
    providers = _get_providers()

    # Map PIDs to their listening ports
    pid_port_map: Dict[int, Set[int]] = {}
    try:
        for conn in psutil.net_connections(kind='tcp'):
            if conn.status == 'LISTEN' and conn.pid:
                if conn.pid not in pid_port_map:
                    pid_port_map[conn.pid] = set()
                pid_port_map[conn.pid].add(conn.laddr.port)
    except psutil.AccessDenied:
        log.warning("Access denied reading network connections.")

    for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
        try:
            proc_name = proc.info.get('name')
            if not proc_name:
                continue

            proc_name_lower = proc_name.lower()
            cmdline_list = proc.info.get('cmdline') or []
            cmdline_str = " ".join(cmdline_list).lower()

            for ProviderClass in providers:
                name_match = any(pname.lower() == proc_name_lower for pname in ProviderClass.PROCESS_NAMES)
                if not name_match:
                    continue

                # Filter out excluded arguments
                if any(excl in cmdline_str for excl in ProviderClass.ARGS_EXCLUDE):
                    continue

                # Filter by required arguments
                if ProviderClass.ARGS_HINTS and not any(hint in cmdline_str for hint in ProviderClass.ARGS_HINTS):
                    continue

                if proc.info['pid'] not in seen_pids:
                    seen_pids.add(proc.info['pid'])

                    # Determine the port
                    port = _extract_port_from_args(cmdline_str)
                    if not port:
                        listening_ports = pid_port_map.get(proc.info['pid'], set())
                        matching_ports = listening_ports.intersection(ProviderClass.DEFAULT_PORTS)
                        if matching_ports:
                            port = matching_ports.pop()
                        elif listening_ports:
                            port = listening_ports.pop()
                        elif ProviderClass.DEFAULT_PORTS:
                            port = ProviderClass.DEFAULT_PORTS[0]

                    # Instantiate the provider
                    provider_instance = ProviderClass(
                        pid=proc.info['pid'],
                        port=port,
                        cmdline=cmdline_list
                    )

                    active_runtimes.append(provider_instance)
                    log.info(f"Discovered runtime: {provider_instance.ENGINE_NAME} (PID: {proc.info['pid']}, Port: {port})")

        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            continue

    return active_runtimes

def _extract_port_from_args(cmdline_str: str) -> Optional[int]:
    patterns = [r"--port\s+(\d+)", r"-p\s+(\d+)", r"--host.*?(\d{4,5})"]
    for pattern in patterns:
        match = re.search(pattern, cmdline_str)
        if match:
            return int(match.group(1))
    return None