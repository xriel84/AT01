"""Analytics reader tests — 12 tests covering read_messages, mark_message,
apply_recommendations, and the /api/analytics_inbox + /api/analytics/mark endpoints.

All tests use temp bus files (no real bus file access).
"""

import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

_tools_dir = str(Path(__file__).resolve().parent.parent / "agents" / "edbot" / "tools")
if _tools_dir not in sys.path:
    sys.path.insert(0, _tools_dir)

from analytics_reader import (
    read_messages,
    mark_message,
    apply_recommendations,
    VALID_TYPES,
    VALID_STATUSES,
)
from fastapi.testclient import TestClient
from agents.edbot.server import app, _cache, _session


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _clear_state():
    _cache["chunks"] = None
    _cache["silence_map"] = None
    _cache["last_input"] = None
    for key in _session:
        _session[key] = None
    yield


@pytest.fixture()
def client():
    return TestClient(app)


def _write_bus(tmp_path, messages):
    """Write a bus file with given messages and return its path."""
    bus = tmp_path / "test-bus.json"
    bus.write_text(json.dumps({"messages": messages}), encoding="utf-8")
    return str(bus)


SAMPLE_MESSAGES = [
    {"id": "fb-001", "type": "FEEDBACK", "status": "unread",
     "subject": "Audio levels low", "body": "Consider normalizing audio",
     "recommendation": "Normalize to -14 LUFS"},
    {"id": "fb-002", "type": "FEEDBACK", "status": "unread",
     "subject": "Good pacing", "body": "Chapter breaks are well placed"},
    {"id": "rq-001", "type": "REQUEST", "status": "unread",
     "subject": "Re-render at 4K"},
    {"id": "fb-003", "type": "FEEDBACK", "status": "read",
     "subject": "Already read message", "body": "Old feedback"},
    {"id": "rp-001", "type": "REPORT", "status": "unread",
     "subject": "Weekly summary"},
]


# ---------------------------------------------------------------------------
# 1. read_messages tests (4)
# ---------------------------------------------------------------------------

class TestReadMessages:

    def test_read_all_unread(self, tmp_path):
        """Read all unread messages regardless of type."""
        bus = _write_bus(tmp_path, SAMPLE_MESSAGES)
        result = read_messages(bus, unread_only=True)
        assert len(result) == 4  # fb-001, fb-002, rq-001, rp-001

    def test_filter_by_type(self, tmp_path):
        """Filter messages by FEEDBACK type."""
        bus = _write_bus(tmp_path, SAMPLE_MESSAGES)
        result = read_messages(bus, filter_type="FEEDBACK", unread_only=True)
        assert len(result) == 2  # fb-001, fb-002
        assert all(m["type"] == "FEEDBACK" for m in result)

    def test_include_read_messages(self, tmp_path):
        """When unread_only=False, include already-read messages."""
        bus = _write_bus(tmp_path, SAMPLE_MESSAGES)
        result = read_messages(bus, filter_type="FEEDBACK", unread_only=False)
        assert len(result) == 3  # fb-001, fb-002, fb-003

    def test_missing_bus_file(self):
        """Missing bus file returns empty list (no crash)."""
        result = read_messages("nonexistent/path.json")
        assert result == []

    def test_invalid_filter_type(self, tmp_path):
        """Invalid filter_type returns empty list."""
        bus = _write_bus(tmp_path, SAMPLE_MESSAGES)
        result = read_messages(bus, filter_type="INVALID")
        assert result == []

    def test_malformed_messages_skipped(self, tmp_path):
        """Messages missing required fields are skipped."""
        messages = [
            {"id": "ok", "type": "FEEDBACK", "status": "unread"},
            {"id": "", "type": "FEEDBACK", "status": "unread"},  # empty id
            {"type": "FEEDBACK", "status": "unread"},  # missing id
            "not a dict",
        ]
        bus = _write_bus(tmp_path, messages)
        result = read_messages(bus, unread_only=True)
        assert len(result) == 1
        assert result[0]["id"] == "ok"


# ---------------------------------------------------------------------------
# 2. mark_message tests (3)
# ---------------------------------------------------------------------------

class TestMarkMessage:

    def test_mark_as_read(self, tmp_path):
        """mark_message changes status to 'read'."""
        bus = _write_bus(tmp_path, SAMPLE_MESSAGES)
        result = mark_message(bus, "fb-001", "read")
        assert result["id"] == "fb-001"
        assert result["status"] == "read"

        # Verify file was updated
        with open(bus, encoding="utf-8") as f:
            data = json.load(f)
        msg = next(m for m in data["messages"] if m["id"] == "fb-001")
        assert msg["status"] == "read"

    def test_mark_invalid_status(self, tmp_path):
        """mark_message rejects invalid status values."""
        bus = _write_bus(tmp_path, SAMPLE_MESSAGES)
        result = mark_message(bus, "fb-001", "deleted")
        assert result.get("code") == "INVALID_INPUT"

    def test_mark_missing_message(self, tmp_path):
        """mark_message returns NOT_FOUND for missing message ID."""
        bus = _write_bus(tmp_path, SAMPLE_MESSAGES)
        result = mark_message(bus, "nonexistent-id", "read")
        assert result.get("code") == "NOT_FOUND"


# ---------------------------------------------------------------------------
# 3. apply_recommendations tests (3)
# ---------------------------------------------------------------------------

class TestApplyRecommendations:

    def test_apply_marks_as_read(self, tmp_path):
        """apply_recommendations reads feedback and marks as read."""
        bus = _write_bus(tmp_path, SAMPLE_MESSAGES)
        result = apply_recommendations(bus)
        # fb-001 and fb-002 are unread FEEDBACK
        assert result["count"] == 2
        assert len(result["applied"]) == 2
        assert result["errors"] == 0

    def test_apply_empty_bus(self, tmp_path):
        """apply_recommendations on empty bus returns zero counts."""
        bus = _write_bus(tmp_path, [])
        result = apply_recommendations(bus)
        assert result["count"] == 0
        assert result["applied"] == []

    def test_apply_extracts_recommendation(self, tmp_path):
        """apply_recommendations extracts recommendation field."""
        bus = _write_bus(tmp_path, SAMPLE_MESSAGES)
        result = apply_recommendations(bus)
        rec = next(r for r in result["applied"] if r["id"] == "fb-001")
        assert rec["recommendation"] == "Normalize to -14 LUFS"


# ---------------------------------------------------------------------------
# 4. Server endpoint tests (2)
# ---------------------------------------------------------------------------

class TestAnalyticsEndpoints:

    def test_analytics_inbox_endpoint(self, client, tmp_path):
        """GET /api/analytics_inbox returns unread feedback."""
        bus = _write_bus(tmp_path, SAMPLE_MESSAGES)
        with patch("agents.edbot.server.read_messages",
                    wraps=lambda **kw: read_messages(bus, **kw)):
            resp = client.get("/api/analytics_inbox")
        assert resp.status_code == 200
        data = resp.json()
        assert "messages" in data
        assert "count" in data

    def test_analytics_mark_endpoint(self, client, tmp_path):
        """POST /api/analytics/mark marks a message."""
        bus = _write_bus(tmp_path, SAMPLE_MESSAGES)
        with patch("agents.edbot.server.mark_message",
                    side_effect=lambda bus_path, message_id, new_status: mark_message(
                        bus, message_id, new_status)):
            resp = client.post("/api/analytics/mark", json={
                "message_id": "fb-001",
                "new_status": "read",
            })
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == "fb-001"
        assert data["status"] == "read"
