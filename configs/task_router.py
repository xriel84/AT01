"""Task router — resolves task config for current machine's GPU tier."""
import json
from pathlib import Path
from configs.gpu_config import get_gpu_tier

ROUTES_PATH = Path(__file__).parent / "task_routing.json"


def load_routes() -> dict:
    """Load all task routes from JSON config."""
    with open(ROUTES_PATH) as f:
        return json.load(f)["routes"]


def get_task_config(task_name: str) -> dict:
    """Return task config for this machine's GPU tier. Walks down tiers."""
    routes = load_routes()
    if task_name not in routes:
        return {"error": f"Unknown task: {task_name}"}

    tiers = routes[task_name]["tiers"]
    current_tier = get_gpu_tier()

    for t in range(current_tier, -1, -1):
        key = str(t)
        if key in tiers:
            return {**tiers[key], "tier_used": t, "task": task_name}

    return {"error": f"No config for {task_name}", "task": task_name}


def get_all_task_configs() -> dict:
    """Return resolved configs for all tasks on current machine."""
    routes = load_routes()
    return {name: get_task_config(name) for name in routes}
