"""GPU status checker for whisper model selection.

Detects available VRAM, checks if DaVinci Resolve is consuming GPU resources,
and recommends optimal whisper model + compute type configuration.
"""

import logging
import subprocess
from typing import Any

import torch

logger = logging.getLogger(__name__)


def check_gpu() -> dict[str, Any]:
    """Check GPU status: VRAM availability and Resolve process.

    Returns dict with keys: cuda_available, total_vram_mb, free_vram_mb,
    resolve_running, device.
    """
    result: dict[str, Any] = {
        "cuda_available": False,
        "total_vram_mb": 0,
        "free_vram_mb": 0,
        "resolve_running": False,
        "device": "cpu",
    }

    # Check CUDA
    try:
        if torch.cuda.is_available():
            result["cuda_available"] = True
            result["device"] = "cuda"
            free, total = torch.cuda.mem_get_info(0)
            result["total_vram_mb"] = round(total / (1024 * 1024))
            result["free_vram_mb"] = round(free / (1024 * 1024))
    except (RuntimeError, AssertionError):
        pass

    # Check Resolve process
    try:
        proc = subprocess.run(
            ["powershell", "-Command",
             "Get-Process -Name 'Resolve' -ErrorAction SilentlyContinue | Select-Object -First 1 | ForEach-Object { $_.Id }"],
            capture_output=True, text=True, timeout=5,
        )
        result["resolve_running"] = bool(proc.stdout.strip())
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        pass

    return result


def recommend_whisper_config(gpu_status: dict[str, Any] | None = None) -> dict[str, Any]:
    """Recommend optimal whisper model + compute type based on GPU status.

    Decision logic:
        free_vram >= 6GB AND no Resolve → float16 + large-v3 (fastest)
        free_vram >= 3GB                → int8_float16 + large-v3 (reliable)
        free_vram >= 1.5GB              → int8_float16 + medium (fast, good quality)
        free_vram < 1.5GB or no CUDA    → cpu + small (last resort)

    Returns dict with keys: model_size, compute_type, device, reason.
    """
    if gpu_status is None:
        gpu_status = check_gpu()

    if not gpu_status.get("cuda_available"):
        return {
            "model_size": "small",
            "compute_type": "int8",
            "device": "cpu",
            "reason": "CUDA not available",
        }

    free_mb = gpu_status.get("free_vram_mb", 0)
    resolve = gpu_status.get("resolve_running", False)

    if free_mb >= 6144 and not resolve:
        return {
            "model_size": "large-v3",
            "compute_type": "float16",
            "device": "cuda",
            "reason": f"plenty of VRAM ({free_mb}MB free, no Resolve)",
        }

    if free_mb >= 3072:
        return {
            "model_size": "large-v3",
            "compute_type": "int8_float16",
            "device": "cuda",
            "reason": f"moderate VRAM ({free_mb}MB free" + (", Resolve running" if resolve else "") + ")",
        }

    if free_mb >= 1536:
        return {
            "model_size": "medium",
            "compute_type": "int8_float16",
            "device": "cuda",
            "reason": f"low VRAM ({free_mb}MB free" + (", Resolve running" if resolve else "") + ")",
        }

    return {
        "model_size": "small",
        "compute_type": "int8",
        "device": "cpu",
        "reason": f"insufficient VRAM ({free_mb}MB free)",
    }
