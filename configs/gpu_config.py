"""GPU capability config loader.

Each machine declares its GPU tier and capabilities in a JSON file.
Tests and task routing read this at runtime to skip/route appropriately.

Tier 0: No GPU (CPU only)
Tier 1: Standard GPU 8-24GB (RTX 4080 class)
Tier 2: Workstation GPU 24GB+ (RTX A6000 class)
"""
import json
import os
import socket
from pathlib import Path
from typing import Optional

_CONFIG_CACHE: Optional[dict] = None
CONFIG_DIR = Path(__file__).parent


def _detect_machine_id() -> str:
    """Detect machine ID from env var or hostname."""
    mid = os.environ.get("AT01_MACHINE_ID", "")
    if mid:
        return mid
    hostname = socket.gethostname().lower()
    if "enki" in hostname:
        return "rielt"
    return "yd"


def get_gpu_config(machine_id: Optional[str] = None) -> dict:
    """Load GPU config for the specified or detected machine."""
    global _CONFIG_CACHE
    if _CONFIG_CACHE is not None and not machine_id:
        return _CONFIG_CACHE

    mid = machine_id or _detect_machine_id()
    candidates = [
        CONFIG_DIR / f"gpu_capabilities_{mid}.json",
        CONFIG_DIR / "gpu_capabilities.json",
    ]
    for path in candidates:
        if path.exists():
            with open(path, encoding="utf-8") as f:
                config = json.load(f)
            if not machine_id:
                _CONFIG_CACHE = config
            return config

    return {"gpu": {"tier": 0, "vram_gb": 0}, "machine_id": "unknown"}


def get_gpu_tier() -> int:
    """Return the GPU tier (0, 1, or 2) for this machine."""
    return get_gpu_config().get("gpu", {}).get("tier", 0)


def get_vram_gb() -> int:
    """Return VRAM in GB for this machine."""
    return get_gpu_config().get("gpu", {}).get("vram_gb", 0)


def get_whisper_config() -> tuple:
    """Return (model_name, compute_type) for whisper on this machine."""
    ml = get_gpu_config().get("ml_capabilities", {})
    return ml.get("whisper_model", "small"), ml.get("whisper_compute", "int8")


def get_ollama_config() -> dict:
    """Return Ollama connection config for this machine."""
    return get_gpu_config().get("ollama", {"host": "127.0.0.1", "port": 11434})


def can_run(capability: str) -> bool:
    """Check if this machine can run the given ML capability."""
    ml = get_gpu_config().get("ml_capabilities", {})
    return ml.get(capability) is True


def reset_cache() -> None:
    """Clear the config cache (for testing)."""
    global _CONFIG_CACHE
    _CONFIG_CACHE = None
