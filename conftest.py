import pytest
from configs.gpu_config import get_gpu_tier, get_vram_gb


def pytest_configure(config):
    """Register GPU-aware pytest markers."""
    config.addinivalue_line("markers", "gpu_tier_1: requires GPU tier 1+ (8-24GB)")
    config.addinivalue_line("markers", "gpu_tier_2: requires GPU tier 2 (24GB+)")
    config.addinivalue_line("markers", "vram_min(gb): requires minimum VRAM in GB")
    config.addinivalue_line("markers", "needs_ollama: requires local Ollama running")
    config.addinivalue_line("markers", "needs_resolve: requires DaVinci Resolve running")
    config.addinivalue_line("markers", "needs_comfyui: requires ComfyUI running")


def pytest_collection_modifyitems(config, items):
    """Auto-skip tests based on GPU tier and VRAM availability."""
    tier = get_gpu_tier()
    vram = get_vram_gb()

    for item in items:
        if item.get_closest_marker("gpu_tier_2") and tier < 2:
            item.add_marker(pytest.mark.skip(
                reason=f"Requires GPU tier 2 (24GB+), machine is tier {tier} ({vram}GB)"
            ))
        if item.get_closest_marker("gpu_tier_1") and tier < 1:
            item.add_marker(pytest.mark.skip(
                reason=f"Requires GPU tier 1+ (8GB+), machine is tier {tier}"
            ))
        vram_marker = item.get_closest_marker("vram_min")
        if vram_marker and vram_marker.args:
            required = vram_marker.args[0]
            if vram < required:
                item.add_marker(pytest.mark.skip(
                    reason=f"Requires {required}GB VRAM, machine has {vram}GB"
                ))
