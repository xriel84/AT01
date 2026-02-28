"""Tests for resolve_decisions — schema validation, executor dry-run, error handling.

All tests use mocked Resolve (no live Resolve dependency).
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

_tools_dir = str(Path(__file__).resolve().parent.parent / "tools")
if _tools_dir not in sys.path:
    sys.path.insert(0, _tools_dir)

from resolve_decisions import (
    VALID_COLORS,
    AddMarkerDecision,
    AddToTimelineDecision,
    CreateSubclipDecision,
    DecisionEnvelope,
    SetClipColorDecision,
    validate_decisions,
    execute_decisions,
    _describe_decision,
    _ExecutionContext,
    _HANDLERS,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_envelope(decisions: list[dict], fps: float = 24.0) -> dict:
    """Build a minimal valid decisions envelope."""
    return {
        "generated_by": "test",
        "generated_at": "2026-02-27T00:00:00Z",
        "fps": fps,
        "decisions": decisions,
    }


def _valid_add_marker() -> dict:
    return {"type": "add_marker", "frame_in": 48, "color": "Blue", "name": "Ch1"}


def _valid_set_clip_color() -> dict:
    return {"type": "set_clip_color", "entry_filename": "clip01.mp4", "color": "Green"}


def _valid_create_subclip() -> dict:
    return {
        "type": "create_subclip", "entry_filename": "clip01.mp4",
        "frame_in": 0, "frame_out": 100, "subclip_name": "Intro",
    }


def _valid_add_to_timeline() -> dict:
    return {
        "type": "add_to_timeline", "entry_filename": "clip01.mp4",
        "frame_in": 0, "frame_out": 200,
    }


# ===========================================================================
# Schema validation — AddMarkerDecision (4)
# ===========================================================================

class TestAddMarkerSchema:
    def test_valid_minimal(self):
        """AddMarkerDecision accepts minimal valid input."""
        d = AddMarkerDecision(frame_in=0, color="Blue", name="Test")
        assert d.frame_in == 0
        assert d.duration == 1
        assert d.marker_target == "timeline"

    def test_invalid_color(self):
        """AddMarkerDecision rejects invalid color."""
        with pytest.raises(ValueError, match="Invalid color"):
            AddMarkerDecision(frame_in=0, color="Magenta", name="Bad")

    def test_negative_frame(self):
        """AddMarkerDecision rejects negative frame_in."""
        with pytest.raises(ValueError):
            AddMarkerDecision(frame_in=-1, color="Blue", name="Neg")

    def test_clip_marker_needs_filename(self):
        """AddMarkerDecision requires entry_filename when targeting a clip."""
        with pytest.raises(ValueError, match="entry_filename required"):
            AddMarkerDecision(
                frame_in=0, color="Blue", name="Clip", marker_target="clip"
            )


# ===========================================================================
# Schema validation — SetClipColorDecision (2)
# ===========================================================================

class TestSetClipColorSchema:
    def test_valid(self):
        """SetClipColorDecision accepts valid input."""
        d = SetClipColorDecision(entry_filename="clip.mp4", color="Red")
        assert d.color == "Red"

    def test_invalid_color(self):
        """SetClipColorDecision rejects invalid color."""
        with pytest.raises(ValueError, match="Invalid color"):
            SetClipColorDecision(entry_filename="clip.mp4", color="Neon")


# ===========================================================================
# Schema validation — CreateSubclipDecision (2)
# ===========================================================================

class TestCreateSubclipSchema:
    def test_valid(self):
        """CreateSubclipDecision accepts valid input."""
        d = CreateSubclipDecision(
            entry_filename="v.mp4", frame_in=10, frame_out=100,
            subclip_name="Part A",
        )
        assert d.frame_out == 100

    def test_frame_out_before_in(self):
        """CreateSubclipDecision rejects frame_out < frame_in."""
        with pytest.raises(ValueError, match="frame_out.*must be >= frame_in"):
            CreateSubclipDecision(
                entry_filename="v.mp4", frame_in=100, frame_out=50,
                subclip_name="Bad",
            )


# ===========================================================================
# Schema validation — AddToTimelineDecision (2)
# ===========================================================================

class TestAddToTimelineSchema:
    def test_valid(self):
        """AddToTimelineDecision accepts valid input."""
        d = AddToTimelineDecision(
            entry_filename="v.mp4", frame_in=0, frame_out=500,
        )
        assert d.track_index == 1

    def test_frame_out_before_in(self):
        """AddToTimelineDecision rejects frame_out < frame_in."""
        with pytest.raises(ValueError, match="frame_out.*must be >= frame_in"):
            AddToTimelineDecision(
                entry_filename="v.mp4", frame_in=200, frame_out=100,
            )


# ===========================================================================
# Envelope validation (4)
# ===========================================================================

class TestValidateDecisions:
    def test_valid_envelope(self):
        """validate_decisions passes a fully valid envelope."""
        data = _make_envelope([_valid_add_marker()])
        valid, errors = validate_decisions(data)
        assert valid is True
        assert errors == []

    def test_missing_fps(self):
        """validate_decisions catches missing fps."""
        data = {"generated_by": "t", "generated_at": "now", "decisions": [_valid_add_marker()]}
        valid, errors = validate_decisions(data)
        assert valid is False
        assert any("fps" in e.lower() or "Envelope" in e for e in errors)

    def test_unknown_decision_type(self):
        """validate_decisions catches unknown decision type."""
        data = _make_envelope([{"type": "delete_everything"}])
        valid, errors = validate_decisions(data)
        assert valid is False
        assert any("unknown type" in e.lower() for e in errors)

    def test_decision_missing_type(self):
        """validate_decisions catches decision without type field."""
        data = _make_envelope([{"frame_in": 0, "color": "Blue"}])
        valid, errors = validate_decisions(data)
        assert valid is False
        assert any("missing 'type'" in e.lower() for e in errors)

    def test_invalid_decision_fields(self):
        """validate_decisions catches bad fields inside a known type."""
        data = _make_envelope([{"type": "add_marker", "frame_in": -5, "color": "Blue", "name": "X"}])
        valid, errors = validate_decisions(data)
        assert valid is False

    def test_empty_decisions_list(self):
        """validate_decisions rejects empty decisions list."""
        data = {
            "generated_by": "t", "generated_at": "now", "fps": 24.0,
            "decisions": [],
        }
        valid, errors = validate_decisions(data)
        assert valid is False


# ===========================================================================
# Executor dry-run (4)
# ===========================================================================

class TestExecutorDryRun:
    def test_dry_run_add_marker(self):
        """Dry-run of add_marker reports planned status."""
        data = _make_envelope([_valid_add_marker()])
        result = execute_decisions(data, mode="dry-run")
        assert result["mode"] == "dry-run"
        assert result["succeeded"] == 1
        assert result["failed"] == 0
        assert result["details"][0]["status"] == "planned"

    def test_dry_run_all_types(self):
        """Dry-run handles all four decision types."""
        data = _make_envelope([
            _valid_add_marker(),
            _valid_set_clip_color(),
            _valid_create_subclip(),
            _valid_add_to_timeline(),
        ])
        result = execute_decisions(data, mode="dry-run")
        assert result["succeeded"] == 4
        assert all(d["status"] == "planned" for d in result["details"])

    def test_confirm_mode_same_as_dry_run(self):
        """Confirm mode returns plan without executing (same shape as dry-run)."""
        data = _make_envelope([_valid_add_marker()])
        result = execute_decisions(data, mode="confirm")
        assert result["mode"] == "confirm"
        assert result["succeeded"] == 1
        assert result["details"][0]["status"] == "planned"

    def test_dry_run_unknown_type_skipped(self):
        """Dry-run skips unknown decision types gracefully."""
        data = _make_envelope([
            _valid_add_marker(),
            {"type": "add_marker", "frame_in": 0, "color": "Blue", "name": "X"},
        ])
        # Inject an unknown type after validation (bypass schema check for executor path)
        data["decisions"].append({"type": "explode"})
        # Re-validate will catch it, so test via executor which validates first
        result = execute_decisions(data, mode="dry-run")
        # Validation catches unknown type -> fails
        assert result["failed"] > 0


# ===========================================================================
# Executor error handling (3)
# ===========================================================================

class TestExecutorErrors:
    def test_invalid_mode(self):
        """Executor rejects invalid mode string."""
        data = _make_envelope([_valid_add_marker()])
        result = execute_decisions(data, mode="yolo")
        assert result["failed"] == 0  # no decisions processed
        assert result["details"][0]["status"] == "error"
        assert "Invalid mode" in result["details"][0]["message"]

    def test_validation_failure(self):
        """Executor returns errors when schema validation fails."""
        data = {"bad": "data"}
        result = execute_decisions(data, mode="dry-run")
        assert result["failed"] > 0
        assert result["succeeded"] == 0

    def test_execute_mode_connection_failure(self):
        """Execute mode handles Resolve connection failure gracefully."""
        data = _make_envelope([_valid_add_marker()])
        # No Resolve running, no mock — connect() will fail
        mock_dvr = MagicMock()
        mock_dvr.scriptapp.return_value = None

        with patch.dict("sys.modules", {"DaVinciResolveScript": mock_dvr}):
            result = execute_decisions(data, mode="execute")

        assert result["failed"] > 0
        assert any("connection" in d.get("message", "").lower()
                    for d in result["details"])


# ===========================================================================
# Executor execute mode — mocked Resolve (3)
# ===========================================================================

def _build_mock_resolve():
    """Build a full mock Resolve API chain."""
    mock_resolve = MagicMock()
    mock_pm = MagicMock()
    mock_project = MagicMock()
    mock_timeline = MagicMock()
    mock_media_pool = MagicMock()
    mock_root_folder = MagicMock()

    mock_resolve.GetProjectManager.return_value = mock_pm
    mock_pm.GetCurrentProject.return_value = mock_project
    mock_project.GetCurrentTimeline.return_value = mock_timeline
    mock_project.GetMediaPool.return_value = mock_media_pool
    mock_media_pool.GetRootFolder.return_value = mock_root_folder

    # Empty clip list by default
    mock_root_folder.GetClipList.return_value = []
    mock_root_folder.GetSubFolderList.return_value = []

    # AddMarker succeeds
    mock_timeline.AddMarker.return_value = True

    return mock_resolve, mock_timeline, mock_media_pool, mock_root_folder


class TestExecutorExecuteMode:
    def test_add_marker_succeeds(self):
        """Execute mode adds marker via timeline.AddMarker()."""
        mock_resolve, mock_timeline, _, _ = _build_mock_resolve()
        data = _make_envelope([_valid_add_marker()])
        result = execute_decisions(data, mode="execute", resolve_connector=mock_resolve)

        assert result["succeeded"] == 1
        assert result["failed"] == 0
        mock_timeline.AddMarker.assert_called_once_with(48, "Blue", "Ch1", "", 1)

    def test_add_marker_returns_false(self):
        """Execute mode reports failure when AddMarker returns False."""
        mock_resolve, mock_timeline, _, _ = _build_mock_resolve()
        mock_timeline.AddMarker.return_value = False
        data = _make_envelope([_valid_add_marker()])
        result = execute_decisions(data, mode="execute", resolve_connector=mock_resolve)

        assert result["failed"] == 1
        assert result["succeeded"] == 0

    def test_handler_exception_caught(self):
        """Execute mode catches handler exceptions without crashing batch."""
        mock_resolve, mock_timeline, _, _ = _build_mock_resolve()
        mock_timeline.AddMarker.side_effect = Exception("Resolve IPC error")
        data = _make_envelope([
            _valid_add_marker(),
        ])
        result = execute_decisions(data, mode="execute", resolve_connector=mock_resolve)

        assert result["failed"] == 1
        assert "Handler exception" in result["details"][0]["message"]


# ===========================================================================
# Clip index building (2)
# ===========================================================================

class TestClipIndex:
    def test_builds_index_from_media_pool(self):
        """_ExecutionContext builds clip index from media pool traversal."""
        mock_resolve, _, _, mock_root = _build_mock_resolve()

        mock_clip1 = MagicMock()
        mock_clip1.GetClipProperty.return_value = r"C:\media\clip01.mp4"
        mock_clip2 = MagicMock()
        mock_clip2.GetClipProperty.return_value = r"C:\media\clip02.mov"
        mock_root.GetClipList.return_value = [mock_clip1, mock_clip2]

        ctx = _ExecutionContext(mock_resolve)
        ctx.connect()

        assert "clip01.mp4" in ctx.clip_index
        assert "clip02.mov" in ctx.clip_index

    def test_set_clip_color_uses_index(self):
        """set_clip_color handler finds clip via index and calls SetClipColor."""
        mock_resolve, _, _, mock_root = _build_mock_resolve()

        mock_clip = MagicMock()
        mock_clip.GetClipProperty.return_value = r"C:\media\clip01.mp4"
        mock_clip.SetClipColor.return_value = True
        mock_root.GetClipList.return_value = [mock_clip]

        data = _make_envelope([_valid_set_clip_color()])
        result = execute_decisions(data, mode="execute", resolve_connector=mock_resolve)

        assert result["succeeded"] == 1
        mock_clip.SetClipColor.assert_called_once_with("Green")


# ===========================================================================
# Describe decision helper (1)
# ===========================================================================

class TestDescribeDecision:
    def test_all_types_described(self):
        """_describe_decision returns non-empty string for all known types."""
        for fixture_fn in [_valid_add_marker, _valid_set_clip_color,
                           _valid_create_subclip, _valid_add_to_timeline]:
            desc = _describe_decision(fixture_fn())
            assert len(desc) > 10
            assert "?" not in desc  # all fields should be filled


# ===========================================================================
# Results JSON structure (1)
# ===========================================================================

class TestResultsStructure:
    def test_result_has_required_keys(self):
        """Executor result always has succeeded/failed/skipped/mode/details."""
        data = _make_envelope([_valid_add_marker()])
        result = execute_decisions(data, mode="dry-run")
        assert "succeeded" in result
        assert "failed" in result
        assert "skipped" in result
        assert "mode" in result
        assert "details" in result
        assert isinstance(result["details"], list)

    def test_detail_entry_structure(self):
        """Each detail entry has index, type, status, message."""
        data = _make_envelope([_valid_add_marker()])
        result = execute_decisions(data, mode="dry-run")
        entry = result["details"][0]
        assert "index" in entry
        assert "type" in entry
        assert "status" in entry
        assert "message" in entry


# ===========================================================================
# VALID_COLORS constant (1)
# ===========================================================================

class TestConstants:
    def test_valid_colors_complete(self):
        """VALID_COLORS contains all 8 Resolve marker colors."""
        assert len(VALID_COLORS) == 8
        assert "Blue" in VALID_COLORS
        assert "Red" in VALID_COLORS
        assert "Purple" in VALID_COLORS


# ===========================================================================
# Live Resolve tests (skip-decorated) — require Resolve running (4)
# ===========================================================================

def _resolve_live() -> bool:
    """Check if Resolve scripting API is reachable."""
    try:
        from resolve_bridge import connect
        connect()
        return True
    except (RuntimeError, ImportError, OSError):
        return False


_HAS_RESOLVE = _resolve_live()

_skip_no_resolve = pytest.mark.skipif(
    not _HAS_RESOLVE, reason="Resolve not running"
)


@_skip_no_resolve
class TestResolveLiveDecisions:
    """Live tests for resolve_decisions against running Resolve."""

    def test_dry_run_against_live_resolve(self):
        """Dry-run with live Resolve connector succeeds without executing."""
        from resolve_bridge import connect
        data = _make_envelope([{
            "type": "add_marker", "frame_in": 0,
            "color": "Blue", "name": "DRYTEST", "note": "live dry-run",
        }])
        result = execute_decisions(data, mode="dry-run")
        assert result["succeeded"] == 1
        assert result["mode"] == "dry-run"

    def test_clip_index_populated(self):
        """Live clip index has at least one entry."""
        from resolve_bridge import connect
        resolve = connect()
        ctx = _ExecutionContext(resolve)
        ctx.connect()
        assert len(ctx.clip_index) >= 1

    def test_timeline_fps_read(self):
        """Live timeline FPS is read as a float."""
        from resolve_bridge import connect
        resolve = connect()
        ctx = _ExecutionContext(resolve)
        ctx.connect()
        assert ctx.timeline_fps is not None
        assert isinstance(ctx.timeline_fps, float)
        assert ctx.timeline_fps > 0

    def test_set_clip_color_returns_true(self):
        """SetClipColor returns True on a live media pool clip."""
        from resolve_bridge import connect
        resolve = connect()
        ctx = _ExecutionContext(resolve)
        ctx.connect()
        if not ctx.clip_index:
            pytest.skip("No clips in media pool")

        filename = next(iter(ctx.clip_index))
        clip = ctx.clip_index[filename]
        result = clip.SetClipColor("Blue")
        assert result is True
