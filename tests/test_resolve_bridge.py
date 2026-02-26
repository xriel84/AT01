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
    resolve_available,
    list_projects,
    create_timeline_from_video,
    add_markers_from_chapters,
    render_timeline,
    get_render_status,
    _render_jobs,
    RENDER_PRESETS,
)
from executor import execute_action
from fastapi.testclient import TestClient
from agents.edbot.server import app, _cache, _session


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


# ===========================================================================
# Session 6: resolve_available tests (2)
# ===========================================================================

def test_resolve_available_when_connected():
    """resolve_available returns available=True when Resolve is reachable."""
    mock_dvr = MagicMock()
    mock_resolve = MagicMock()
    mock_resolve.GetProductName.return_value = "DaVinci Resolve Studio"
    mock_resolve.GetVersion.return_value = [20, 3, 1, ""]
    mock_dvr.scriptapp.return_value = mock_resolve

    with patch.dict("sys.modules", {"DaVinciResolveScript": mock_dvr}):
        result = resolve_available()

    assert result["available"] is True
    assert result["version"] == "20.3.1"
    assert result["product"] == "DaVinci Resolve Studio"
    assert result["error"] is None


def test_resolve_available_when_offline():
    """resolve_available returns available=False when Resolve is unreachable."""
    mock_dvr = MagicMock()
    mock_dvr.scriptapp.return_value = None

    with patch.dict("sys.modules", {"DaVinciResolveScript": mock_dvr}):
        result = resolve_available()

    assert result["available"] is False
    assert result["version"] is None
    assert "Resolve" in result["error"]


# ===========================================================================
# Session 6: list_projects tests (2)
# ===========================================================================

def test_list_projects_success():
    """list_projects returns project names and current project."""
    mock_dvr = MagicMock()
    mock_resolve = MagicMock()
    mock_pm = MagicMock()
    mock_pm.GetProjectListInCurrentFolder.return_value = ["Project A", "Project B"]
    mock_project = MagicMock()
    mock_project.GetName.return_value = "Project A"
    mock_pm.GetCurrentProject.return_value = mock_project
    mock_resolve.GetProjectManager.return_value = mock_pm
    mock_dvr.scriptapp.return_value = mock_resolve

    with patch.dict("sys.modules", {"DaVinciResolveScript": mock_dvr}):
        result = list_projects()

    assert result["projects"] == ["Project A", "Project B"]
    assert result["current"] == "Project A"
    assert result["count"] == 2
    assert result["error"] is None


def test_list_projects_offline():
    """list_projects returns error dict when Resolve is offline."""
    mock_dvr = MagicMock()
    mock_dvr.scriptapp.return_value = None

    with patch.dict("sys.modules", {"DaVinciResolveScript": mock_dvr}):
        result = list_projects()

    assert result["projects"] == []
    assert result["count"] == 0
    assert result["error"] is not None


# ===========================================================================
# Session 6: create_timeline_from_video tests (3)
# ===========================================================================

def test_create_timeline_file_not_found():
    """create_timeline_from_video returns error for missing file."""
    result = create_timeline_from_video("C:/nonexistent/video.mp4")
    assert result["success"] is False
    assert "not found" in result["error"]


def test_create_timeline_success(tmp_path):
    """create_timeline_from_video creates timeline from video file."""
    video = tmp_path / "test.mp4"
    video.write_bytes(b"\x00" * 100)

    mock_dvr = MagicMock()
    mock_resolve = MagicMock()
    mock_pm = MagicMock()
    mock_project = MagicMock()
    mock_pool = MagicMock()
    mock_pool.ImportMedia.return_value = [MagicMock()]
    mock_tl = MagicMock()
    mock_tl.GetName.return_value = "test"
    mock_pool.CreateTimelineFromClips.return_value = mock_tl
    mock_project.GetMediaPool.return_value = mock_pool
    mock_pm.GetCurrentProject.return_value = mock_project
    mock_resolve.GetProjectManager.return_value = mock_pm
    mock_dvr.scriptapp.return_value = mock_resolve

    with patch.dict("sys.modules", {"DaVinciResolveScript": mock_dvr}):
        result = create_timeline_from_video(str(video))

    assert result["success"] is True
    assert result["timeline_name"] == "test"


def test_create_timeline_custom_name(tmp_path):
    """create_timeline_from_video uses custom timeline name."""
    video = tmp_path / "test.mp4"
    video.write_bytes(b"\x00" * 100)

    mock_dvr = MagicMock()
    mock_resolve = MagicMock()
    mock_pm = MagicMock()
    mock_project = MagicMock()
    mock_pool = MagicMock()
    mock_pool.ImportMedia.return_value = [MagicMock()]
    mock_tl = MagicMock()
    mock_tl.GetName.return_value = "My Custom TL"
    mock_pool.CreateTimelineFromClips.return_value = mock_tl
    mock_project.GetMediaPool.return_value = mock_pool
    mock_pm.GetCurrentProject.return_value = mock_project
    mock_resolve.GetProjectManager.return_value = mock_pm
    mock_dvr.scriptapp.return_value = mock_resolve

    with patch.dict("sys.modules", {"DaVinciResolveScript": mock_dvr}):
        result = create_timeline_from_video(str(video), "My Custom TL")

    assert result["success"] is True
    mock_pool.CreateTimelineFromClips.assert_called_once()


# ===========================================================================
# Session 6: add_markers_from_chapters tests (3)
# ===========================================================================

def test_add_markers_empty_chapters():
    """add_markers_from_chapters returns error for empty chapter list."""
    result = add_markers_from_chapters([])
    assert result["success"] is False
    assert "no chapters" in result["error"]


def test_add_markers_success():
    """add_markers_from_chapters adds markers to current timeline."""
    chapters = [
        {"title": "Intro", "start": 0, "summary": "Opening remarks"},
        {"title": "Main", "start": 60, "summary": "Core content"},
        {"title": "Outro", "start": 300, "summary": "Closing"},
    ]

    mock_dvr = MagicMock()
    mock_resolve = MagicMock()
    mock_pm = MagicMock()
    mock_project = MagicMock()
    mock_tl = MagicMock()
    mock_tl.AddMarker.return_value = True
    mock_project.GetCurrentTimeline.return_value = mock_tl
    mock_pm.GetCurrentProject.return_value = mock_project
    mock_resolve.GetProjectManager.return_value = mock_pm
    mock_dvr.scriptapp.return_value = mock_resolve

    with patch.dict("sys.modules", {"DaVinciResolveScript": mock_dvr}):
        result = add_markers_from_chapters(chapters)

    assert result["success"] is True
    assert result["markers_added"] == 3
    assert mock_tl.AddMarker.call_count == 3


def test_add_markers_named_timeline():
    """add_markers_from_chapters finds timeline by name."""
    chapters = [{"title": "Test", "start": 10, "summary": ""}]

    mock_dvr = MagicMock()
    mock_resolve = MagicMock()
    mock_pm = MagicMock()
    mock_project = MagicMock()
    mock_project.GetTimelineCount.return_value = 2
    mock_tl_1 = MagicMock()
    mock_tl_1.GetName.return_value = "Other"
    mock_tl_2 = MagicMock()
    mock_tl_2.GetName.return_value = "Target TL"
    mock_tl_2.AddMarker.return_value = True
    mock_project.GetTimelineByIndex.side_effect = lambda i: [None, mock_tl_1, mock_tl_2][i]
    mock_pm.GetCurrentProject.return_value = mock_project
    mock_resolve.GetProjectManager.return_value = mock_pm
    mock_dvr.scriptapp.return_value = mock_resolve

    with patch.dict("sys.modules", {"DaVinciResolveScript": mock_dvr}):
        result = add_markers_from_chapters(chapters, timeline_name="Target TL")

    assert result["success"] is True
    assert result["markers_added"] == 1


# ===========================================================================
# Session 6: render_timeline + get_render_status tests (3)
# ===========================================================================

def test_render_timeline_creates_job():
    """render_timeline creates a tracked job entry."""
    _render_jobs.clear()

    # Mock resolve_export to return failure (no Resolve)
    with patch("resolve_bridge.resolve_export", return_value={
        "success": False, "output_path": None, "elapsed_seconds": 0.1,
        "error": "Timeline not found: FakeTL",
    }):
        result = render_timeline("FakeTL", "output/test.mp4")

    assert result["status"] == "failed"
    assert result["id"] is not None
    assert len(_render_jobs) == 1


def test_render_timeline_success():
    """render_timeline returns complete status on success."""
    _render_jobs.clear()

    with patch("resolve_bridge.resolve_export", return_value={
        "success": True, "output_path": "output/test.mp4",
        "elapsed_seconds": 12.5, "error": None,
    }):
        result = render_timeline("Main Edit", "output/test.mp4")

    assert result["status"] == "complete"
    assert result["elapsed_seconds"] == 12.5


def test_get_render_status_not_found():
    """get_render_status returns error for unknown job ID."""
    _render_jobs.clear()
    result = get_render_status("nonexistent")
    assert result["status"] == "error"
    assert "not found" in result["error"]


def test_get_render_status_all_jobs():
    """get_render_status with no ID returns all jobs."""
    _render_jobs.clear()
    _render_jobs["abc"] = {"id": "abc", "status": "complete"}
    _render_jobs["def"] = {"id": "def", "status": "failed"}

    result = get_render_status()
    assert result["count"] == 2
    assert len(result["jobs"]) == 2


# ===========================================================================
# Session 6: Server endpoint integration tests (5)
# ===========================================================================

@pytest.fixture(autouse=True)
def _clear_server_state():
    _cache["chunks"] = None
    _cache["silence_map"] = None
    _cache["last_input"] = None
    for key in _session:
        _session[key] = None
    yield


@pytest.fixture()
def client():
    return TestClient(app)


def test_resolve_status_endpoint(client):
    """GET /api/resolve/status returns availability info."""
    with patch("agents.edbot.server.resolve_available", return_value={
        "available": False, "version": None, "product": None,
        "error": "Resolve not running",
    }):
        resp = client.get("/api/resolve/status")
    assert resp.status_code == 200
    data = resp.json()
    assert data["available"] is False


def test_resolve_status_endpoint_online(client):
    """GET /api/resolve/status returns version when online."""
    with patch("agents.edbot.server.resolve_available", return_value={
        "available": True, "version": "20.3.1",
        "product": "DaVinci Resolve Studio", "error": None,
    }):
        resp = client.get("/api/resolve/status")
    assert resp.status_code == 200
    data = resp.json()
    assert data["available"] is True
    assert data["version"] == "20.3.1"


def test_resolve_timeline_endpoint_missing_file(client):
    """POST /api/resolve/timeline returns 400 for missing file."""
    resp = client.post("/api/resolve/timeline", json={
        "video_path": "C:/nonexistent/video.mp4",
    })
    assert resp.status_code == 400


def test_resolve_markers_endpoint_empty(client):
    """POST /api/resolve/markers returns 400 for empty chapters."""
    resp = client.post("/api/resolve/markers", json={
        "chapters": [],
    })
    assert resp.status_code == 400


def test_resolve_render_status_not_found(client):
    """GET /api/resolve/render/{job_id} returns 404 for unknown job."""
    _render_jobs.clear()
    with patch("agents.edbot.server.get_render_status",
               return_value={"status": "error", "error": "job not found: xyz"}):
        resp = client.get("/api/resolve/render/xyz")
    assert resp.status_code == 404
