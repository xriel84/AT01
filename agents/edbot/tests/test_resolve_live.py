"""Live Resolve integration tests. Skip when Resolve not running."""

import os
import time
import pytest
import sys

sys.path.insert(0, "agents/edbot/tools")


def _resolve_live():
    try:
        from resolve_bridge import resolve_available

        result = resolve_available()
        return result.get("available", False)
    except Exception:
        return False


skip_no_resolve = pytest.mark.skipif(
    not _resolve_live(),
    reason="Resolve not running",
)


@skip_no_resolve
class TestResolveLive:
    def test_available(self):
        from resolve_bridge import resolve_available

        result = resolve_available()
        assert result["available"] is True
        assert result["error"] is None
        assert result["product"] == "DaVinci Resolve Studio"

    def test_version_string(self):
        from resolve_bridge import resolve_available

        result = resolve_available()
        assert result["version"] is not None
        parts = result["version"].split(".")
        assert len(parts) >= 3

    def test_list_projects(self):
        from resolve_bridge import list_projects

        result = list_projects()
        assert isinstance(result["projects"], list)
        assert result["count"] >= 1
        assert result["current"] is not None
        assert result["error"] is None

    def test_create_timeline(self):
        from resolve_bridge import create_timeline_from_video

        # Use unique name to avoid duplicate-timeline rejection
        unique_name = f"pytest_live_{int(time.time())}"
        result = create_timeline_from_video(
            r"C:\AT01\input\IMG_5769.MOV",
            unique_name,
        )
        assert result is not None
        assert result["success"] is True, f"Timeline creation failed: {result}"
        assert result["timeline_name"] == unique_name
        assert result["error"] is None

    def test_add_markers(self):
        from resolve_bridge import add_markers_from_chapters

        # Use high frame offsets to avoid conflicts with existing markers
        ts = int(time.time()) % 10000
        chapters = [
            {"title": f"Test A {ts}", "start": 100.0 + ts % 50, "summary": "A"},
            {"title": f"Test B {ts}", "start": 200.0 + ts % 50, "summary": "B"},
        ]
        result = add_markers_from_chapters(chapters)
        assert result is not None
        assert result["success"] is True
        assert result["markers_added"] >= 1
        assert result["error"] is None

    def test_get_resolve_info(self):
        from resolve_bridge import get_resolve_info

        info = get_resolve_info()
        assert "product" in info
        assert "version" in info
        assert "version_string" in info
        assert info["product"] == "DaVinci Resolve Studio"

    def test_connect_returns_object(self):
        from resolve_bridge import connect

        resolve = connect()
        assert resolve is not None
        assert resolve.GetProductName() is not None

    def test_get_current_timeline(self):
        from resolve_bridge import get_current_timeline

        tl = get_current_timeline()
        # May be None if no timeline is active, but should not raise
        if tl is not None:
            assert "name" in tl
            assert "video_tracks" in tl
            assert "audio_tracks" in tl

    def test_list_projects_has_current(self):
        from resolve_bridge import list_projects

        result = list_projects()
        assert result["current"] in result["projects"]

    def test_resolve_available_returns_dict(self):
        from resolve_bridge import resolve_available

        result = resolve_available()
        assert isinstance(result, dict)
        for key in ("available", "version", "product", "error"):
            assert key in result

    def test_list_projects_returns_dict(self):
        from resolve_bridge import list_projects

        result = list_projects()
        assert isinstance(result, dict)
        for key in ("projects", "current", "count", "error"):
            assert key in result

    def test_create_timeline_bad_path(self):
        from resolve_bridge import create_timeline_from_video

        result = create_timeline_from_video(
            r"C:\nonexistent\fake_video.mp4",
            "should_fail",
        )
        assert result["success"] is False
        assert result["error"] is not None

    def test_add_markers_empty_list(self):
        from resolve_bridge import add_markers_from_chapters

        result = add_markers_from_chapters([])
        assert result["success"] is False
        assert result["error"] is not None

    def test_export_timeline_markers(self):
        from resolve_bridge import connect

        resolve = connect()
        pm = resolve.GetProjectManager()
        project = pm.GetCurrentProject()
        timeline = project.GetCurrentTimeline()
        if timeline is not None:
            from resolve_bridge import export_timeline_markers

            markers = export_timeline_markers(timeline)
            assert isinstance(markers, list)

    def test_render_timeline_starts(self):
        """Create timeline from IMG_5769.MOV, start render, verify job_id returned."""
        from resolve_bridge import create_timeline_from_video, render_timeline

        tl_name = f"render_test_{int(time.time())}"
        create_timeline_from_video(r"C:\AT01\input\IMG_5769.MOV", tl_name)
        output = rf"C:\AT01\output\{tl_name}.mp4"
        result = render_timeline(tl_name, output)
        assert result is not None
        assert "id" in result
        assert result["id"] is not None
        # Clean up output file if created
        if os.path.exists(output):
            os.remove(output)

    def test_get_render_status_valid_job(self):
        """After starting render, get_render_status returns status dict."""
        from resolve_bridge import render_timeline, get_render_status

        # Use a known-bad timeline name to get a quick failure (no long render)
        result = render_timeline("nonexistent_timeline_xyz", r"C:\AT01\output\nope.mp4")
        job_id = result.get("id")
        assert job_id is not None
        status = get_render_status(job_id)
        assert "status" in status
        assert status["id"] == job_id

    def test_render_timeline_invalid_timeline(self):
        """Render with bad timeline name returns error dict, no crash."""
        from resolve_bridge import render_timeline

        result = render_timeline("does_not_exist_12345", r"C:\AT01\output\fail.mp4")
        assert result is not None
        assert result["status"] == "failed"
        assert result["error"] is not None

    def test_get_render_status_unknown_job(self):
        """get_render_status with unknown job_id returns error."""
        from resolve_bridge import get_render_status

        result = get_render_status("nonexistent_job_id")
        assert result is not None
        assert result.get("status") == "error"
