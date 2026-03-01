"""Append-only JSONL logger for agent actions.

Tracks cloud vs local token usage over time. Stdlib only.
"""
import json
from datetime import datetime, timezone
from pathlib import Path

METRICS_FILE = Path(__file__).parent / "agent_actions.jsonl"


def log_agent_action(
    agent: str,
    task_type: str,
    task_desc: str,
    model: str,
    tokens_in: int = 0,
    tokens_out: int = 0,
    cost_usd: float = 0.0,
    duration_ms: int = 0,
    source: str = "manual",
    metrics_file: Path | None = None,
) -> None:
    """Append one JSON line to the agent actions log.

    Args:
        agent: Agent identifier (e.g. "claude-code", "goose", "ollama").
        task_type: Category (e.g. "architecture", "nlp", "health").
        task_desc: Short free-text description.
        model: Model used (e.g. "claude-sonnet-4-5", "mistral-nemo").
        tokens_in: Input/prompt token count.
        tokens_out: Output/completion token count.
        cost_usd: Estimated cost in USD.
        duration_ms: Wall-clock duration in milliseconds.
        source: How this was logged ("manual", "hook", "ollama-api").
        metrics_file: Override log file path (for testing).
    """
    try:
        target = metrics_file if metrics_file is not None else METRICS_FILE
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "agent": agent,
            "task_type": task_type,
            "task_desc": task_desc,
            "model": model,
            "tokens_in": tokens_in,
            "tokens_out": tokens_out,
            "cost_usd": cost_usd,
            "duration_ms": duration_ms,
            "source": source,
        }
        with open(target, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")
    except Exception:
        pass
