"""Resolve bridge tests — connection, timeline ops, markers, EDL import, executor path.

Tests that require a running Resolve instance are marked with
@pytest.mark.skipif and will be skipped in CI or when Resolve is not open.
"""

import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

_tools_dir = str(Path(__file__).resolve().parent.parent / "agents" / "edbot" / "tools")
if _tools_dir not in sys.path:
    sys.path.insert(0, _tools_dir)

from resolve_bridge import (
    connect,
    get_resolve_info,
    get_current_timeline,
    get_timeline_clips,
    export_timeline_markers,
    import_edl,
    resolve_export,
    RENDER_PRESETS,
)
from executor import execute_action


# ---------------------------------------------------------------------------
# Helper: detect if Resolve is running
# ---------------------------------------------------------------------------

def _resolve_available() -> bool:
    """Check if Resolve scripting API is reachable."""
    try:
        connect()
        return True
    except (RuntimeError, ImportError, OSError):
        return False


_HAS_RESOLVE = _resolve_available()


# ===========================================================================
# Connection tests (4)
# ===========================================================================

def test_import():
    """resolve_bridge module imports without error."""
    import resolve_bridge
    assert hasattr(resolve_bridge, "connect")
    assert hasattr(resolve_bridge, "resolve_export")


def test_connect_mock():
    """connect() returns Resolve object when scriptapp succeeds."""
    mock_resolve = MagicMock()
    mock_dvr = MagicMock()
    mock_dvr.scriptapp.return_value = mock_resolve

    with patch.dict("sys.modules", {"DaVinciResolveScript": mock_dvr}):
        result = connect()
    assert result is mock_resolve


def test_connect_none_raises():
    """connect() raises RuntimeError when scriptapp returns None."""
    mock_dvr = MagicMock()
    mock_dvr.scriptapp.return_value = None

    with patch.dict("sys.modules", {"DaVinciResolveScript": mock_dvr}):
        with pytest.raises(RuntimeError, match="Resolve running"):
            connect()


def test_get_resolve_info_mock():
    """get_resolve_info() returns product and version dict."""
    mock_resolve = MagicMock()
    mock_resolve.GetProductName.return_value = "DaVinci Resolve Studio"
    mock_resolve.GetVersion.return_value = [20, 3, 1, 6, ""]

    mock_dvr = MagicMock()
    mock_dvr.scriptapp.return_value = mock_resolve

    with patch.dict("sys.modules", {"DaVinciResolveScript": mock_dvr}):
        info = get_resolve_info()

    assert info["product"] == "DaVinci Resolve Studio"
    assert info["version_string"] == "20.3.1.6"


# ===========================================================================
# Live connection tests (2) — require Resolve running
# ===========================================================================

@pytest.mark.skipif(not _HAS_RESOLVE, reason="Resolve not running")
def test_connect_live():
    """Live connection to Resolve returns a non-None object."""
    resolve = connect()
    assert resolve is not None
    assert resolve.GetProductName() is not None


@pytest.mark.skipif(not _HAS_RESOLVE, reason="Resolve not running")
def test_get_resolve_info_live():
    """Live get_resolve_info returns real version data."""
    info = get_resolve_info()
    assert "DaVinci Resolve" in info["product"]
    assert isinstance(info["version_string"], str)


# ===========================================================================
# get_current_timeline tests (3)
# ===========================================================================

def test_get_current_timeline_no_project():
    """get_current_timeline raises RuntimeError when no project open."""
    mock_dvr = MagicMock()
    mock_resolve = MagicMock()
    mock_pm = MagicMock()
    mock_pm.GetCurrentProject.return_value = None
    mock_resolve.GetProjectManager.return_value = mock_pm
    mock_dvr.scriptapp.return_value = mock_resolve

    with patch.dict("sys.modules", {"DaVinciResolveScript": mock_dvr}):
        with pytest.raises(RuntimeError, match="No project open"):
            get_current_timeline()


def test_get_current_timeline_no_timeline():
    """get_current_timeline returns None when project has no active timeline."""
    mock_dvr = MagicMock()
    mock_resolve = MagicMock()
    mock_pm = MagicMock()
    mock_project = MagicMock()
    mock_project.GetCurrentTimeline.return_value = None
    mock_pm.GetCurrentProject.return_value = mock_project
    mock_resolve.GetProjectManager.return_value = mock_pm
    mock_dvr.scriptapp.return_value = mock_resolve

    with patch.dict("sys.modules", {"DaVinciResolveScript": mock_dvr}):
        result = get_current_timeline()
    assert result is None


def test_get_current_timeline_with_data():
    """get_current_timeline returns dict with timeline metadata."""
    mock_dvr = MagicMock()
    mock_resolve = MagicMock()
    mock_pm = MagicMock()
    mock_project = MagicMock()
    mock_tl = MagicMock()
    mock_tl.GetName.return_value = "Main Edit"
    mock_tl.GetTrackCount.side_effect = lambda t: 2 if t == "video" else 4
    mock_tl.GetStartFrame.return_value = 0
    mock_tl.GetEndFrame.return_value = 7200
    mock_project.GetCurrentTimeline.return_value = mock_tl
    mock_pm.GetCurrentProject.return_value = mock_project
    mock_resolve.GetProjectManager.return_value = mock_pm
    mock_dvr.scriptapp.return_value = mock_resolve

    with patch.dict("sys.modules", {"DaVinciResolveScript": mock_dvr}):
        result = get_current_timeline()

    assert result["name"] == "Main Edit"
    assert result["video_tracks"] == 2
    assert result["audio_tracks"] == 4
    assert result["end_frame"] == 7200


# ===========================================================================
# get_timeline_clips tests (3)
# ===========================================================================

def test_get_timeline_clips_none_raises():
    """get_timeline_clips raises RuntimeError for None timeline."""
    with pytest.raises(RuntimeError, match="Timeline is None"):
        get_timeline_clips(None)


def test_get_timeline_clips_empty():
    """get_timeline_clips returns [] for timeline with no clips."""
    mock_tl = MagicMock()
    mock_tl.GetTrackCount.return_value = 1
    mock_tl.GetItemListInTrack.return_value = []

    result = get_timeline_clips(mock_tl)
    assert result == []


def test_get_timeline_clips_with_items():
    """get_timeline_clips returns clip dicts with correct fields."""
    mock_item = MagicMock()
    mock_item.GetName.return_value = "Clip_001"
    mock_item.GetStart.return_value = 0
    mock_item.GetEnd.return_value = 150
    mock_item.GetDuration.return_value = 150
    mock_mpi = MagicMock()
    mock_mpi.GetClipProperty.return_value = "C:/media/clip1.mp4"
    mock_item.GetMediaPoolItem.return_value = mock_mpi

    mock_tl = MagicMock()
    mock_tl.GetTrackCount.return_value = 1
    mock_tl.GetItemListInTrack.return_value = [mock_item]

    result = get_timeline_clips(mock_tl)
    assert len(result) == 1
    assert result[0]["name"] == "Clip_001"
    assert result[0]["duration"] == 150
    assert result[0]["track"] == 1
    assert result[0]["media_path"] == "C:/media/clip1.mp4"


# ===========================================================================
# export_timeline_markers tests (3)
# ===========================================================================

def test_export_markers_none_raises():
    """export_timeline_markers raises RuntimeError for None timeline."""
    with pytest.raises(RuntimeError, match="Timeline is None"):
        export_timeline_markers(None)


def test_export_markers_empty():
    """export_timeline_markers returns [] when no markers exist."""
    mock_tl = MagicMock()
    mock_tl.GetMarkers.return_value = {}

    result = export_timeline_markers(mock_tl)
    assert result == []


def test_export_markers_with_data():
    """export_timeline_markers returns sorted marker dicts."""
    mock_tl = MagicMock()
    mock_tl.GetMarkers.return_value = {
        100: {"color": "Blue", "name": "Intro", "note": "Start here", "duration": 1},
        500: {"color": "Red", "name": "Cut", "note": "Hard cut", "duration": 1},
        300: {"color": "Green", "name": "Mid", "note": "", "duration": 5},
    }

    result = export_timeline_markers(mock_tl)
    assert len(result) == 3
    # Sorted by frame
    assert result[0]["frame"] == 100
    assert result[1]["frame"] == 300
    assert result[2]["frame"] == 500
    assert result[0]["color"] == "Blue"
    assert result[2]["name"] == "Cut"


# ===========================================================================
# import_edl tests (4)
# ===========================================================================

def test_import_edl_no_project():
    """import_edl returns error dict when project is None."""
    result = import_edl(None, "test.edl")
    assert result["success"] is False
    assert "No project" in result["error"]


def test_import_edl_file_not_found():
    """import_edl returns error when EDL file doesn't exist."""
    mock_project = MagicMock()
    result = import_edl(mock_project, "C:/nonexistent/file.edl")
    assert result["success"] is False
    assert "not found" in result["error"]


def test_import_edl_bad_extension(tmp_path):
    """import_edl rejects non-EDL file types."""
    txt_file = tmp_path / "notes.txt"
    txt_file.write_text("hello", encoding="utf-8")

    mock_project = MagicMock()
    result = import_edl(mock_project, str(txt_file))
    assert result["success"] is False
    assert "Unsupported" in result["error"]


def test_import_edl_success(tmp_path):
    """import_edl returns success with timeline name on valid EDL."""
    edl_file = tmp_path / "test.edl"
    edl_file.write_text("TITLE: Test EDL\n", encoding="utf-8")

    mock_timeline = MagicMock()
    mock_timeline.GetName.return_value = "Test EDL"
    mock_mp = MagicMock()
    mock_mp.ImportTimelineFromFile.return_value = mock_timeline
    mock_project = MagicMock()
    mock_project.GetMediaPool.return_value = mock_mp

    result = import_edl(mock_project, str(edl_file))
    assert result["success"] is True
    assert result["timeline_name"] == "Test EDL"
    assert result["error"] is None


# ===========================================================================
# resolve_export tests (4)
# ===========================================================================

def test_resolve_export_bad_preset():
    """resolve_export returns error for unknown preset."""
    result = resolve_export("Timeline 1", "output/test.mp4", preset="fake_preset")
    assert result["success"] is False
    assert "Unknown preset" in result["error"]


def test_resolve_export_timeline_not_found():
    """resolve_export returns error when timeline name doesn't match."""
    mock_dvr = MagicMock()
    mock_resolve = MagicMock()
    mock_pm = MagicMock()
    mock_project = MagicMock()
    mock_project.GetTimelineCount.return_value = 1
    mock_tl = MagicMock()
    mock_tl.GetName.return_value = "Other Timeline"
    mock_project.GetTimelineByIndex.return_value = mock_tl
    mock_pm.GetCurrentProject.return_value = mock_project
    mock_resolve.GetProjectManager.return_value = mock_pm
    mock_dvr.scriptapp.return_value = mock_resolve

    with patch.dict("sys.modules", {"DaVinciResolveScript": mock_dvr}):
        result = resolve_export("Missing Timeline", "output/test.mp4")

    assert result["success"] is False
    assert "not found" in result["error"]


def test_resolve_export_render_succeeds(tmp_path):
    """resolve_export returns success when render completes and file exists."""
    out_file = tmp_path / "render.mp4"
    out_file.write_bytes(b"\x00" * 1024)  # fake output

    mock_dvr = MagicMock()
    mock_resolve = MagicMock()
    mock_pm = MagicMock()
    mock_project = MagicMock()
    mock_project.GetTimelineCount.return_value = 1
    mock_tl = MagicMock()
    mock_tl.GetName.return_value = "My Timeline"
    mock_project.GetTimelineByIndex.return_value = mock_tl
    mock_project.AddRenderJob.return_value = "job_1"
    mock_project.IsRenderingInProgress.return_value = False
    mock_pm.GetCurrentProject.return_value = mock_project
    mock_resolve.GetProjectManager.return_value = mock_pm
    mock_dvr.scriptapp.return_value = mock_resolve

    with patch.dict("sys.modules", {"DaVinciResolveScript": mock_dvr}):
        result = resolve_export("My Timeline", str(out_file))

    assert result["success"] is True
    assert result["error"] is None


def test_resolve_export_add_job_fails():
    """resolve_export returns error when AddRenderJob fails."""
    mock_dvr = MagicMock()
    mock_resolve = MagicMock()
    mock_pm = MagicMock()
    mock_project = MagicMock()
    mock_project.GetTimelineCount.return_value = 1
    mock_tl = MagicMock()
    mock_tl.GetName.return_value = "Timeline 1"
    mock_project.GetTimelineByIndex.return_value = mock_tl
    mock_project.AddRenderJob.return_value = None
    mock_pm.GetCurrentProject.return_value = mock_project
    mock_resolve.GetProjectManager.return_value = mock_pm
    mock_dvr.scriptapp.return_value = mock_resolve

    with patch.dict("sys.modules", {"DaVinciResolveScript": mock_dvr}):
        result = resolve_export("Timeline 1", "output/test.mp4")

    assert result["success"] is False
    assert "Failed to add render job" in result["error"]


# ===========================================================================
# Executor resolve_export dispatch tests (3)
# ===========================================================================

def test_executor_resolve_export_no_timeline_name():
    """resolve_export via executor with no timeline_name returns error."""
    action = {
        "action": "resolve_export",
        "params": {"input": "C:/AT01/input/test.mp4"},
        "executor": "resolve",
    }
    result = execute_action(action)
    assert result["status"] == "error"
    assert "timeline_name" in result["error"]


def test_executor_resolve_export_bridge_not_available():
    """resolve_export via executor returns error when bridge unavailable."""
    action = {
        "action": "resolve_export",
        "params": {"input": "C:/AT01/input/test.mp4", "timeline_name": "TL1"},
        "executor": "resolve",
    }
    with patch("executor._resolve_export", None):
        result = execute_action(action)
    assert result["status"] == "error"
    assert "not available" in result["error"]


def test_executor_resolve_export_dispatches():
    """resolve_export via executor calls resolve_bridge.resolve_export."""
    action = {
        "action": "resolve_export",
        "params": {
            "input": "C:/AT01/input/test.mp4",
            "timeline_name": "Main Edit",
            "preset": "h264_mp4",
        },
        "executor": "resolve",
    }
    mock_result = {"success": True, "output_path": "output/test.mp4", "elapsed_seconds": 5.0, "error": None}
    with patch("executor._resolve_export", return_value=mock_result), \
         patch("executor._get_duration", return_value=60.0):
        result = execute_action(action)
    assert result["status"] == "success"
    assert result["action"] == "resolve_export"


# ===========================================================================
# Live Resolve tests (2) — require Resolve running
# ===========================================================================

@pytest.mark.skipif(not _HAS_RESOLVE, reason="Resolve not running")
def test_get_current_timeline_live():
    """Live get_current_timeline returns dict or None."""
    result = get_current_timeline()
    # May be None if no timeline exists — that's valid
    if result is not None:
        assert "name" in result
        assert "video_tracks" in result


@pytest.mark.skipif(not _HAS_RESOLVE, reason="Resolve not running")
def test_render_presets_keys():
    """RENDER_PRESETS has expected keys."""
    assert "h264_mp4" in RENDER_PRESETS
    assert "prores_mov" in RENDER_PRESETS
    for preset in RENDER_PRESETS.values():
        assert "format" in preset
        assert "codec" in preset
