"""EdBot Resolve bridge — connects to DaVinci Resolve Studio via native scripting API.

Uses DaVinciResolveScript (shipped with Resolve) to control the application.
pybmd has a type annotation bug with Python 3.12 so we use the native API directly.

Requires: DaVinci Resolve Studio running on the same machine.
Scripting API: C:\\ProgramData\\Blackmagic Design\\DaVinci Resolve\\Support\\Developer\\Scripting\\Modules
"""

import logging
import sys
import time
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Resolve scripting module path
# ---------------------------------------------------------------------------

_RESOLVE_SCRIPT_PATH = (
    r"C:\ProgramData\Blackmagic Design\DaVinci Resolve"
    r"\Support\Developer\Scripting\Modules"
)

if _RESOLVE_SCRIPT_PATH not in sys.path:
    sys.path.append(_RESOLVE_SCRIPT_PATH)


# ---------------------------------------------------------------------------
# Connection
# ---------------------------------------------------------------------------

def connect() -> Any:
    """Connect to running DaVinci Resolve instance.

    Returns the Resolve object, or raises RuntimeError if Resolve is not
    running or the scripting API is unavailable.
    """
    try:
        import DaVinciResolveScript as dvr
    except ImportError as exc:
        raise RuntimeError(
            f"DaVinciResolveScript not found at {_RESOLVE_SCRIPT_PATH}: {exc}"
        ) from exc

    resolve = dvr.scriptapp("Resolve")
    if resolve is None:
        raise RuntimeError(
            "Resolve scripting returned None — is DaVinci Resolve running?"
        )
    return resolve


def _get_current_project() -> Any:
    """Get the current project from Resolve. Raises RuntimeError if none open."""
    resolve = connect()
    pm = resolve.GetProjectManager()
    project = pm.GetCurrentProject()
    if project is None:
        raise RuntimeError("No project open in Resolve")
    return project


def get_resolve_info() -> dict[str, Any]:
    """Return Resolve product name and version as a dict.

    Returns dict with keys: product, version, version_string.
    Raises RuntimeError if Resolve is not reachable.
    """
    resolve = connect()
    version = resolve.GetVersion()
    version_str = ".".join(str(v) for v in version if v != "")
    return {
        "product": resolve.GetProductName(),
        "version": version,
        "version_string": version_str,
    }


# ---------------------------------------------------------------------------
# Timeline operations
# ---------------------------------------------------------------------------

def get_current_timeline() -> Optional[dict[str, Any]]:
    """Get the current timeline from the active project.

    Returns dict with timeline metadata (name, video_tracks, audio_tracks,
    start_frame, end_frame) or None if no timeline is active.
    """
    project = _get_current_project()
    timeline = project.GetCurrentTimeline()
    if timeline is None:
        return None

    return {
        "name": timeline.GetName(),
        "video_tracks": timeline.GetTrackCount("video"),
        "audio_tracks": timeline.GetTrackCount("audio"),
        "start_frame": timeline.GetStartFrame(),
        "end_frame": timeline.GetEndFrame(),
    }


def get_timeline_clips(timeline: Any) -> list[dict[str, Any]]:
    """Get all clips from a timeline's video tracks.

    Args:
        timeline: Resolve Timeline object (from project.GetCurrentTimeline()).

    Returns list of clip dicts with: name, start, end, duration, track,
    media_path (if available).
    """
    if timeline is None:
        raise RuntimeError("Timeline is None — no active timeline in Resolve")

    clips: list[dict[str, Any]] = []
    video_track_count = timeline.GetTrackCount("video")

    for track_idx in range(1, video_track_count + 1):
        items = timeline.GetItemListInTrack("video", track_idx)
        if not items:
            continue
        for item in items:
            clip: dict[str, Any] = {
                "name": item.GetName(),
                "start": item.GetStart(),
                "end": item.GetEnd(),
                "duration": item.GetDuration(),
                "track": track_idx,
            }
            # Try to get source media path
            mpi = item.GetMediaPoolItem()
            if mpi is not None:
                clip["media_path"] = mpi.GetClipProperty("File Path") or None
            else:
                clip["media_path"] = None
            clips.append(clip)

    return clips


def export_timeline_markers(timeline: Any) -> list[dict[str, Any]]:
    """Export all markers from a timeline.

    Args:
        timeline: Resolve Timeline object.

    Returns list of marker dicts with: frame, color, name, note, duration.
    Markers are sorted by frame number.
    """
    if timeline is None:
        raise RuntimeError("Timeline is None — no active timeline in Resolve")

    raw_markers = timeline.GetMarkers()
    if not raw_markers:
        return []

    markers: list[dict[str, Any]] = []
    for frame_id, marker_data in sorted(raw_markers.items()):
        markers.append({
            "frame": frame_id,
            "color": marker_data.get("color", ""),
            "name": marker_data.get("name", ""),
            "note": marker_data.get("note", ""),
            "duration": marker_data.get("duration", 1),
        })

    return markers


def import_edl(project: Any, edl_path: str) -> dict[str, Any]:
    """Import an EDL file into a Resolve project's media pool.

    Args:
        project: Resolve Project object (from pm.GetCurrentProject()).
        edl_path: Absolute path to the EDL file.

    Returns dict with: success, timeline_name, error.
    """
    if project is None:
        return {"success": False, "timeline_name": None, "error": "No project provided"}

    p = Path(edl_path)
    if not p.exists():
        return {"success": False, "timeline_name": None, "error": f"EDL file not found: {edl_path}"}

    if p.suffix.lower() not in (".edl", ".xml", ".fcpxml", ".aaf"):
        return {
            "success": False,
            "timeline_name": None,
            "error": f"Unsupported file type: {p.suffix} (expected .edl, .xml, .fcpxml, .aaf)",
        }

    media_pool = project.GetMediaPool()
    if media_pool is None:
        return {"success": False, "timeline_name": None, "error": "Could not access media pool"}

    timeline = media_pool.ImportTimelineFromFile(str(p))
    if timeline is None:
        return {
            "success": False,
            "timeline_name": None,
            "error": f"Resolve failed to import EDL: {edl_path}",
        }

    return {
        "success": True,
        "timeline_name": timeline.GetName(),
        "error": None,
    }


# ---------------------------------------------------------------------------
# Render / export
# ---------------------------------------------------------------------------

# Resolve render presets mapping friendly names to format+codec pairs.
RENDER_PRESETS: dict[str, dict[str, str]] = {
    "h264_mp4":   {"format": "mp4", "codec": "H264"},
    "h265_mp4":   {"format": "mp4", "codec": "H265"},
    "prores_mov": {"format": "mov", "codec": "ProRes422"},
    "dnxhd_mxf":  {"format": "mxf", "codec": "DNxHD"},
}


def resolve_export(
    timeline_name: str,
    output_path: str,
    preset: str = "h264_mp4",
) -> dict[str, Any]:
    """Render a timeline from Resolve to an output file.

    Finds the timeline by name, sets render settings, adds a render job,
    starts rendering, and waits for completion.

    Args:
        timeline_name: Name of the timeline to render.
        output_path: Full output file path.
        preset: One of RENDER_PRESETS keys (default: h264_mp4).

    Returns dict with: success, output_path, elapsed_seconds, error.
    """
    t0 = time.perf_counter()

    if preset not in RENDER_PRESETS:
        return {
            "success": False,
            "output_path": None,
            "elapsed_seconds": round(time.perf_counter() - t0, 3),
            "error": f"Unknown preset: {preset} (available: {list(RENDER_PRESETS.keys())})",
        }

    project = _get_current_project()

    # Find timeline by name
    timeline = None
    for i in range(1, project.GetTimelineCount() + 1):
        tl = project.GetTimelineByIndex(i)
        if tl and tl.GetName() == timeline_name:
            timeline = tl
            break

    if timeline is None:
        return {
            "success": False,
            "output_path": None,
            "elapsed_seconds": round(time.perf_counter() - t0, 3),
            "error": f"Timeline not found: {timeline_name}",
        }

    # Set as current timeline
    project.SetCurrentTimeline(timeline)

    # Configure render settings
    out = Path(output_path)
    render_preset = RENDER_PRESETS[preset]

    project.SetCurrentRenderFormatAndCodec(render_preset["format"], render_preset["codec"])
    project.SetRenderSettings({
        "TargetDir": str(out.parent),
        "CustomName": out.stem,
    })

    # Add render job
    job_id = project.AddRenderJob()
    if not job_id:
        return {
            "success": False,
            "output_path": output_path,
            "elapsed_seconds": round(time.perf_counter() - t0, 3),
            "error": "Failed to add render job — check Resolve render settings",
        }

    # Start rendering
    project.StartRendering()

    # Poll for completion (timeout after 10 minutes)
    timeout = 600
    poll_start = time.perf_counter()
    while project.IsRenderingInProgress():
        if time.perf_counter() - poll_start > timeout:
            project.StopRendering()
            return {
                "success": False,
                "output_path": output_path,
                "elapsed_seconds": round(time.perf_counter() - t0, 3),
                "error": f"Render timed out after {timeout}s",
            }
        time.sleep(1)

    elapsed = round(time.perf_counter() - t0, 3)

    # Check if output file exists
    if out.exists():
        return {
            "success": True,
            "output_path": str(out),
            "elapsed_seconds": elapsed,
            "error": None,
        }

    return {
        "success": False,
        "output_path": output_path,
        "elapsed_seconds": elapsed,
        "error": "Render completed but output file not found",
    }


# ---------------------------------------------------------------------------
# Session 6: Higher-level bridge functions
# ---------------------------------------------------------------------------

_render_jobs: dict[str, dict[str, Any]] = {}


def resolve_available() -> dict[str, Any]:
    """Check if DaVinci Resolve is reachable via scripting API.

    Returns dict with: available, version, product, error.
    """
    try:
        info = get_resolve_info()
        return {
            "available": True,
            "version": info.get("version_string"),
            "product": info.get("product"),
            "error": None,
        }
    except RuntimeError as exc:
        return {
            "available": False,
            "version": None,
            "product": None,
            "error": str(exc),
        }


def list_projects() -> dict[str, Any]:
    """List projects in current Resolve database.

    Returns dict with: projects (list of names), current, count, error.
    """
    try:
        resolve = connect()
        pm = resolve.GetProjectManager()
        projects = pm.GetProjectListInCurrentFolder() or []
        current = pm.GetCurrentProject()
        current_name = current.GetName() if current else None
        return {
            "projects": list(projects),
            "current": current_name,
            "count": len(projects),
            "error": None,
        }
    except RuntimeError as exc:
        return {
            "projects": [],
            "current": None,
            "count": 0,
            "error": str(exc),
        }


def create_timeline_from_video(
    video_path: str,
    timeline_name: str | None = None,
) -> dict[str, Any]:
    """Import a video file into Resolve media pool and create a timeline.

    Args:
        video_path: Absolute path to the video file.
        timeline_name: Name for the new timeline. Defaults to video stem.

    Returns dict with: success, timeline_name, error.
    """
    p = Path(video_path)
    if not p.exists():
        return {"success": False, "timeline_name": None, "error": f"file not found: {video_path}"}

    if timeline_name is None:
        timeline_name = p.stem

    try:
        project = _get_current_project()
        media_pool = project.GetMediaPool()
        if media_pool is None:
            return {"success": False, "timeline_name": None, "error": "could not access media pool"}

        media_items = media_pool.ImportMedia([str(p)])
        if not media_items:
            return {"success": False, "timeline_name": None, "error": "media import failed"}

        timeline = media_pool.CreateTimelineFromClips(timeline_name, media_items)
        if timeline is None:
            return {"success": False, "timeline_name": timeline_name, "error": "timeline creation failed"}

        return {
            "success": True,
            "timeline_name": timeline.GetName(),
            "error": None,
        }
    except RuntimeError as exc:
        return {"success": False, "timeline_name": None, "error": str(exc)}


def add_markers_from_chapters(
    chapters: list[dict[str, Any]],
    timeline_name: str | None = None,
    fps: float = 24.0,
) -> dict[str, Any]:
    """Add chapter markers to a Resolve timeline.

    Args:
        chapters: List of chapter dicts with 'title', 'start', 'summary'.
        timeline_name: Target timeline name. Defaults to current timeline.
        fps: Frame rate for converting seconds to frames.

    Returns dict with: success, markers_added, error.
    """
    if not chapters:
        return {"success": False, "markers_added": 0, "error": "no chapters provided"}

    try:
        project = _get_current_project()

        if timeline_name:
            timeline = None
            for i in range(1, project.GetTimelineCount() + 1):
                tl = project.GetTimelineByIndex(i)
                if tl and tl.GetName() == timeline_name:
                    timeline = tl
                    break
            if timeline is None:
                return {"success": False, "markers_added": 0, "error": f"timeline not found: {timeline_name}"}
        else:
            timeline = project.GetCurrentTimeline()
            if timeline is None:
                return {"success": False, "markers_added": 0, "error": "no active timeline"}

        added = 0
        for ch in chapters:
            start_sec = ch.get("start", 0)
            frame = int(start_sec * fps)
            title = ch.get("title", f"Chapter {added + 1}")
            note = ch.get("summary", "")

            success = timeline.AddMarker(frame, "Blue", title, note, 1)
            if success:
                added += 1

        return {
            "success": True,
            "markers_added": added,
            "error": None,
        }
    except RuntimeError as exc:
        return {"success": False, "markers_added": 0, "error": str(exc)}


def render_timeline(
    timeline_name: str,
    output_path: str,
    preset: str = "h264_mp4",
) -> dict[str, Any]:
    """Start a render job for a timeline with job ID tracking.

    Wraps resolve_export and stores result in _render_jobs dict.

    Returns dict with: id, status, timeline, output_path, error.
    """
    import uuid
    job_id = str(uuid.uuid4())[:8]

    _render_jobs[job_id] = {
        "id": job_id,
        "status": "starting",
        "timeline": timeline_name,
        "output_path": output_path,
        "preset": preset,
        "error": None,
    }

    result = resolve_export(timeline_name, output_path, preset)

    if result.get("success"):
        _render_jobs[job_id]["status"] = "complete"
        _render_jobs[job_id]["elapsed_seconds"] = result.get("elapsed_seconds")
    else:
        _render_jobs[job_id]["status"] = "failed"
        _render_jobs[job_id]["error"] = result.get("error")

    return _render_jobs[job_id]


def get_render_status(job_id: str | None = None) -> dict[str, Any]:
    """Get render job status.

    Args:
        job_id: Specific job ID. If None, returns all jobs.

    Returns dict with job info, or list of all jobs.
    """
    if job_id is not None:
        job = _render_jobs.get(job_id)
        if job is None:
            return {"error": f"job not found: {job_id}", "status": "error"}
        return job

    return {
        "jobs": list(_render_jobs.values()),
        "count": len(_render_jobs),
    }
