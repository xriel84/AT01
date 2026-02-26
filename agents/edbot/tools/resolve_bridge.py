"""EdBot Resolve bridge — connects to DaVinci Resolve Studio via native scripting API.

Uses DaVinciResolveScript (shipped with Resolve) to control the application.
pybmd has a type annotation bug with Python 3.12 so we use the native API directly.

Requires: DaVinci Resolve Studio running on the same machine.
Scripting API: C:\\ProgramData\\Blackmagic Design\\DaVinci Resolve\\Support\\Developer\\Scripting\\Modules
"""

import logging
import sys
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
# Timeline operations (placeholder — Round 5 implementation)
# ---------------------------------------------------------------------------

def get_current_timeline() -> Optional[dict[str, Any]]:
    """Get the current timeline from the active project.

    Returns dict with timeline metadata (name, duration, track count, etc.)
    or None if no timeline is active.

    Round 5 implementation target.
    """
    raise NotImplementedError("Round 5: get_current_timeline")


def get_timeline_clips(timeline: Any) -> list[dict[str, Any]]:
    """Get all clips from a timeline.

    Args:
        timeline: Resolve Timeline object.

    Returns list of clip dicts with: name, start, end, duration, track, media_path.

    Round 5 implementation target.
    """
    raise NotImplementedError("Round 5: get_timeline_clips")


def export_timeline_markers(timeline: Any) -> list[dict[str, Any]]:
    """Export all markers from a timeline.

    Args:
        timeline: Resolve Timeline object.

    Returns list of marker dicts with: frame, color, name, note, duration.

    Round 5 implementation target.
    """
    raise NotImplementedError("Round 5: export_timeline_markers")


def import_edl(project: Any, edl_path: str) -> dict[str, Any]:
    """Import an EDL file into a Resolve project.

    Args:
        project: Resolve Project object.
        edl_path: Path to the EDL file.

    Returns dict with: success, timeline_name, clip_count, error.

    Round 5 implementation target.
    """
    raise NotImplementedError("Round 5: import_edl")
