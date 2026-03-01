"""Claude->Ollama delegation helper.

Claude Code CLI uses this to send tasks to local Ollama and evaluate results.
Pattern: Claude plans -> Ollama executes -> Claude evaluates -> log pass/fail.
"""
import json
import time
from pathlib import Path
from datetime import datetime, timezone
from typing import Optional
from configs.gpu_config import get_ollama_config

DELEGATION_LOG = Path(__file__).parent / "ollama_delegation_log.json"


def delegate_to_ollama(
    prompt: str,
    context: str = "",
    model: Optional[str] = None,
    task_type: str = "general",
    timeout: int = 120,
    temperature: float = 0.3,
) -> dict:
    """Send a task to local Ollama and return structured result.

    Args:
        prompt: Instruction for Ollama.
        context: Additional context (transcript, code, etc.).
        model: Override model (None = auto from config).
        task_type: planning|coding|worker|general.
        timeout: Request timeout seconds.
        temperature: Ollama temperature.

    Returns:
        Dict with status, response, model, duration_s, task_type, timestamp.
    """
    ollama_cfg = get_ollama_config()
    host = ollama_cfg.get("host", "127.0.0.1")
    port = ollama_cfg.get("port", 11434)

    if model is None:
        model = _select_model(task_type, ollama_cfg)
    if model is None:
        return _result("error", "No model available for this task type", None, 0, task_type)

    full_prompt = f"{prompt}\n\n{context}" if context else prompt
    start = time.time()

    try:
        import urllib.request
        req = urllib.request.Request(
            f"http://{host}:{port}/api/generate",
            data=json.dumps({
                "model": model,
                "prompt": full_prompt,
                "stream": False,
                "options": {"temperature": temperature},
            }).encode(),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read())
        duration = time.time() - start
        result = _result("pass", data.get("response", ""), model, duration, task_type)
        try:
            from metrics.agent_logger import log_agent_action
            log_agent_action(
                agent="ollama",
                task_type=task_type,
                task_desc=full_prompt[:120],
                model=model,
                tokens_in=data.get("prompt_eval_count", 0),
                tokens_out=data.get("eval_count", 0),
                cost_usd=0.0,
                duration_ms=int(data.get("total_duration", 0) / 1_000_000),
                source="ollama-api",
            )
        except Exception:
            pass
    except Exception as e:
        duration = time.time() - start
        result = _result("error", str(e), model, duration, task_type)

    _log_delegation(result)
    return result


def _select_model(task_type: str, ollama_cfg: dict) -> Optional[str]:
    """Pick the right Ollama model for the task type."""
    mapping = {
        "planning": ollama_cfg.get("max_model_for_planning"),
        "coding": ollama_cfg.get("max_model_for_coding"),
        "worker": ollama_cfg.get("default_worker_model"),
        "general": ollama_cfg.get("default_worker_model"),
    }
    model = mapping.get(task_type, ollama_cfg.get("default_worker_model"))
    if model and str(model).startswith("__"):
        return None
    return model


def _result(
    status: str,
    response: str,
    model: Optional[str],
    duration: float,
    task_type: str,
) -> dict:
    """Build a structured delegation result."""
    return {
        "status": status,
        "response": response,
        "model": model,
        "duration_s": round(duration, 2),
        "task_type": task_type,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


def _log_delegation(result: dict) -> None:
    """Append result to the delegation log (max 200 entries)."""
    try:
        log = []
        if DELEGATION_LOG.exists():
            with open(DELEGATION_LOG, encoding="utf-8") as f:
                log = json.load(f)
        log.append(result)
        if len(log) > 200:
            log = log[-200:]
        with open(DELEGATION_LOG, "w", encoding="utf-8") as f:
            json.dump(log, f, indent=2)
    except Exception:
        pass
