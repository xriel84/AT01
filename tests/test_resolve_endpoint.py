"""Tests for POST /api/resolve/command endpoint.

All tests use mocked Resolve and mocked Ollama — no live dependencies.
"""

import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest
from fastapi.testclient import TestClient

_tools_dir = str(Path(__file__).resolve().parent.parent / "agents" / "edbot" / "tools")
if _tools_dir not in sys.path:
    sys.path.insert(0, _tools_dir)

from agents.edbot.server import app


@pytest.fixture()
def client():
    return TestClient(app)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _valid_decisions_envelope() -> dict:
    """A valid pre-built decisions envelope."""
    return {
        "generated_by": "test",
        "generated_at": "2026-02-27T00:00:00Z",
        "fps": 24.0,
        "decisions": [
            {"type": "add_marker", "frame_in": 48, "color": "Blue",
             "name": "Test Marker", "note": "endpoint test"},
        ],
    }


def _chapter_context() -> dict:
    """Context with chapters for NLP template test."""
    return {
        "chapters": [
            {"title": "Intro", "start": 0, "end": 60},
            {"title": "Main", "start": 60, "end": 180},
        ],
        "fps": 24.0,
    }


# ===========================================================================
# NLP command path (3)
# ===========================================================================

def test_command_dry_run_template(client):
    """POST with NLP command using template path returns plan."""
    resp = client.post("/api/resolve/command", json={
        "command": "mark chapters as blue markers",
        "context": _chapter_context(),
        "mode": "dry-run",
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["mode"] == "dry-run"
    assert data["translation_method"] == "template"
    assert data["plan"] is not None
    assert len(data["plan"]["decisions"]) == 2
    assert data["results"]["succeeded"] == 2


def test_command_dry_run_ollama(client):
    """POST with free-form command uses Ollama path (mocked)."""
    valid_decisions = _valid_decisions_envelope()
    mock_response = {
        "status": "pass",
        "response": __import__("json").dumps(valid_decisions),
        "model": "qwen2.5-coder:14b",
        "duration_s": 2.0,
        "task_type": "coding",
        "timestamp": "2026-02-27T00:00:00Z",
    }
    with patch("ollama_delegate.delegate_to_ollama", return_value=mock_response):
        resp = client.post("/api/resolve/command", json={
            "command": "add a blue marker at frame 48 called Test Marker",
            "context": {"fps": 24.0},
            "mode": "dry-run",
        })
    assert resp.status_code == 200
    data = resp.json()
    assert data["translation_method"] == "ollama"
    assert data["results"]["succeeded"] >= 1


def test_command_translation_failure(client):
    """POST returns 422 when NLP translation fails."""
    mock_error = {
        "status": "error",
        "response": "connection refused",
        "model": None,
        "duration_s": 0.1,
        "task_type": "coding",
        "timestamp": "2026-02-27T00:00:00Z",
    }
    with patch("ollama_delegate.delegate_to_ollama", return_value=mock_error):
        resp = client.post("/api/resolve/command", json={
            "command": "do something",
            "context": {"fps": 24.0},
            "mode": "dry-run",
        })
    assert resp.status_code == 422


# ===========================================================================
# Pre-built decisions path (2)
# ===========================================================================

def test_decisions_dry_run(client):
    """POST with pre-built decisions returns plan."""
    resp = client.post("/api/resolve/command", json={
        "decisions": _valid_decisions_envelope(),
        "mode": "dry-run",
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["mode"] == "dry-run"
    assert data["translation_method"] == "direct"
    assert data["results"]["succeeded"] == 1


def test_decisions_invalid_schema(client):
    """POST with invalid decisions envelope returns 422."""
    resp = client.post("/api/resolve/command", json={
        "decisions": {
            "generated_by": "test",
            "fps": 24.0,
            "decisions": [{"type": "bogus_type"}],
        },
        "mode": "dry-run",
    })
    assert resp.status_code == 422


# ===========================================================================
# Error handling (3)
# ===========================================================================

def test_empty_request(client):
    """POST with neither command nor decisions returns 400."""
    resp = client.post("/api/resolve/command", json={
        "mode": "dry-run",
    })
    assert resp.status_code == 400


def test_invalid_mode(client):
    """POST with invalid mode returns 400."""
    resp = client.post("/api/resolve/command", json={
        "command": "mark chapters as markers",
        "context": _chapter_context(),
        "mode": "yolo",
    })
    assert resp.status_code == 400


def test_missing_body(client):
    """POST with no JSON body returns 422 (Pydantic validation)."""
    resp = client.post("/api/resolve/command")
    # FastAPI returns 422 for missing Content-Type / empty body
    assert resp.status_code == 422


# ===========================================================================
# Response structure (1)
# ===========================================================================

def test_response_structure(client):
    """Response has plan, results, translation_method, mode keys."""
    resp = client.post("/api/resolve/command", json={
        "decisions": _valid_decisions_envelope(),
        "mode": "dry-run",
    })
    assert resp.status_code == 200
    data = resp.json()
    assert "plan" in data
    assert "results" in data
    assert "translation_method" in data
    assert "mode" in data
    # Results has expected keys
    assert "succeeded" in data["results"]
    assert "failed" in data["results"]
    assert "details" in data["results"]


# ===========================================================================
# Resolve lock exists (1)
# ===========================================================================

def test_resolve_lock_exists():
    """Server has an asyncio.Lock for Resolve IPC serialization."""
    from agents.edbot.server import _resolve_lock
    import asyncio
    assert isinstance(_resolve_lock, asyncio.Lock)
