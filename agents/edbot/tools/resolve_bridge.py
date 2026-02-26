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
