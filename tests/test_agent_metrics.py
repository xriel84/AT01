"""Tests for agent metrics JSONL logging."""
import json
from datetime import datetime
from pathlib import Path

import pytest

from metrics.agent_logger import log_agent_action


class TestAgentLogger:
    """Verify append-only JSONL logging for agent actions."""

    def test_creates_file_if_missing(self, tmp_path: Path) -> None:
        """log_agent_action creates JSONL file if it doesn't exist."""
        target = tmp_path / "actions.jsonl"
        assert not target.exists()
        log_agent_action(
            agent="claude-code", task_type="test", task_desc="unit test",
            model="claude-sonnet-4-5", metrics_file=target,
        )
        assert target.exists()

    def test_appends_valid_json_line(self, tmp_path: Path) -> None:
        """Each call appends a valid JSON line."""
        target = tmp_path / "actions.jsonl"
        log_agent_action(
            agent="ollama", task_type="nlp", task_desc="translate command",
            model="mistral-nemo", tokens_in=50, tokens_out=120,
            metrics_file=target,
        )
        line = target.read_text(encoding="utf-8").strip()
        entry = json.loads(line)
        assert entry["agent"] == "ollama"
        assert entry["task_desc"] == "translate command"

    def test_multiple_calls_append_not_overwrite(self, tmp_path: Path) -> None:
        """Multiple calls produce multiple lines, not overwrite."""
        target = tmp_path / "actions.jsonl"
        for i in range(3):
            log_agent_action(
                agent="goose", task_type="probe", task_desc=f"call {i}",
                model="mistral-nemo", metrics_file=target,
            )
        lines = target.read_text(encoding="utf-8").strip().split("\n")
        assert len(lines) == 3
        for i, line in enumerate(lines):
            assert json.loads(line)["task_desc"] == f"call {i}"

    def test_all_required_fields_present(self, tmp_path: Path) -> None:
        """Logged entry must contain all required fields."""
        target = tmp_path / "actions.jsonl"
        log_agent_action(
            agent="claude-code", task_type="architecture",
            task_desc="review handoff", model="claude-sonnet-4-5",
            tokens_in=1000, tokens_out=500, cost_usd=0.02,
            duration_ms=3400, source="manual", metrics_file=target,
        )
        entry = json.loads(target.read_text(encoding="utf-8").strip())
        required = {
            "timestamp", "agent", "task_type", "task_desc", "model",
            "tokens_in", "tokens_out", "cost_usd", "duration_ms", "source",
        }
        missing = required - entry.keys()
        assert not missing, f"Missing fields: {missing}"

    def test_iso8601_timestamp(self, tmp_path: Path) -> None:
        """Timestamp must be valid ISO-8601."""
        target = tmp_path / "actions.jsonl"
        log_agent_action(
            agent="ollama", task_type="health", task_desc="ping",
            model="mistral-nemo", metrics_file=target,
        )
        entry = json.loads(target.read_text(encoding="utf-8").strip())
        ts = datetime.fromisoformat(entry["timestamp"])
        assert ts.tzinfo is not None, "Timestamp must be timezone-aware"

    def test_ollama_cost_zero(self, tmp_path: Path) -> None:
        """cost_usd should be 0.0 for ollama agent entries."""
        target = tmp_path / "actions.jsonl"
        log_agent_action(
            agent="ollama", task_type="nlp", task_desc="chapter markers",
            model="mistral-nemo", cost_usd=0.0, source="ollama-api",
            metrics_file=target,
        )
        entry = json.loads(target.read_text(encoding="utf-8").strip())
        assert entry["cost_usd"] == 0.0

    def test_invalid_agent_string_no_crash(self, tmp_path: Path) -> None:
        """Invalid or unusual agent string still logs without crash."""
        target = tmp_path / "actions.jsonl"
        log_agent_action(
            agent="", task_type="test", task_desc="empty agent",
            model="unknown", metrics_file=target,
        )
        log_agent_action(
            agent="x" * 500, task_type="test", task_desc="long agent",
            model="unknown", metrics_file=target,
        )
        lines = target.read_text(encoding="utf-8").strip().split("\n")
        assert len(lines) == 2

    def test_logging_failure_silent(self, tmp_path: Path) -> None:
        """Logging to an invalid path must not raise."""
        bad_path = tmp_path / "nonexistent_dir" / "deep" / "actions.jsonl"
        # Should not raise — silently fails
        log_agent_action(
            agent="ollama", task_type="nlp", task_desc="should not crash",
            model="mistral-nemo", metrics_file=bad_path,
        )
