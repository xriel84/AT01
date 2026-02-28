"""Resolve edit-decision schema, validator, and executor.

Accepts a structured JSON envelope of editing decisions (add markers, set clip
colors, etc.) and executes them against DaVinci Resolve via resolve_bridge.

Modes:
    dry-run  — validate + log every action, execute nothing (default)
    confirm  — return the validated plan without executing (caller confirms)
    execute  — validate then run all actions against Resolve

CLI usage:
    py -3.12 -m agents.edbot.tools.resolve_decisions <path.json> [--dry-run|--confirm|--execute] [--verbose] [--output results.json]
"""

import argparse
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal, Optional, Union

from pydantic import BaseModel, Field, field_validator, model_validator

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

VALID_COLORS: list[str] = [
    "Blue", "Green", "Yellow", "Red", "Purple", "Cyan", "Pink", "Orange",
]

EXECUTION_MODES = ("dry-run", "confirm", "execute")


# ---------------------------------------------------------------------------
# Decision models (Pydantic v2)
# ---------------------------------------------------------------------------

class AddMarkerDecision(BaseModel):
    """Add a marker to the current timeline (or to a specific clip)."""

    type: Literal["add_marker"] = "add_marker"
    frame_in: int = Field(..., ge=0, description="Start frame for the marker")
    color: str = Field(..., description="Marker color")
    name: str = Field(..., description="Marker name/title")
    note: str = Field(default="", description="Marker note text")
    duration: int = Field(default=1, ge=1, description="Marker duration in frames")
    marker_target: Literal["timeline", "clip"] = Field(
        default="timeline", description="Where to place the marker"
    )
    entry_filename: Optional[str] = Field(
        default=None, description="Clip filename (required when marker_target='clip')"
    )

    @field_validator("color")
    @classmethod
    def validate_color(cls, v: str) -> str:
        """Ensure color is one of the Resolve-supported values."""
        if v not in VALID_COLORS:
            raise ValueError(f"Invalid color '{v}'. Must be one of: {VALID_COLORS}")
        return v

    @model_validator(mode="after")
    def clip_needs_filename(self) -> "AddMarkerDecision":
        """If targeting a clip, entry_filename is required."""
        if self.marker_target == "clip" and not self.entry_filename:
            raise ValueError("entry_filename required when marker_target is 'clip'")
        return self


class SetClipColorDecision(BaseModel):
    """Set the color tag on a media pool clip."""

    type: Literal["set_clip_color"] = "set_clip_color"
    entry_filename: str = Field(..., description="Clip filename to color-tag")
    color: str = Field(..., description="Color tag to apply")

    @field_validator("color")
    @classmethod
    def validate_color(cls, v: str) -> str:
        """Ensure color is one of the Resolve-supported values."""
        if v not in VALID_COLORS:
            raise ValueError(f"Invalid color '{v}'. Must be one of: {VALID_COLORS}")
        return v


class CreateSubclipDecision(BaseModel):
    """Create a subclip from a media pool item with in/out points."""

    type: Literal["create_subclip"] = "create_subclip"
    entry_filename: str = Field(..., description="Source clip filename")
    frame_in: int = Field(..., ge=0, description="Subclip start frame")
    frame_out: int = Field(..., ge=0, description="Subclip end frame")
    subclip_name: str = Field(..., description="Name for the new subclip")
    target_bin: Optional[str] = Field(
        default=None, description="Target bin/folder name"
    )

    @model_validator(mode="after")
    def out_after_in(self) -> "CreateSubclipDecision":
        """frame_out must be >= frame_in."""
        if self.frame_out < self.frame_in:
            raise ValueError(
                f"frame_out ({self.frame_out}) must be >= frame_in ({self.frame_in})"
            )
        return self


class AddToTimelineDecision(BaseModel):
    """Append a media pool clip (or portion) to a timeline."""

    type: Literal["add_to_timeline"] = "add_to_timeline"
    entry_filename: str = Field(..., description="Clip filename to add")
    frame_in: int = Field(..., ge=0, description="Source start frame")
    frame_out: int = Field(..., ge=0, description="Source end frame")
    track_index: int = Field(default=1, ge=1, description="Target video track")
    target_timeline: Optional[str] = Field(
        default=None, description="Timeline name (None = current)"
    )

    @model_validator(mode="after")
    def out_after_in(self) -> "AddToTimelineDecision":
        """frame_out must be >= frame_in."""
        if self.frame_out < self.frame_in:
            raise ValueError(
                f"frame_out ({self.frame_out}) must be >= frame_in ({self.frame_in})"
            )
        return self


# Union of all decision types (discriminated by 'type' field)
Decision = Union[
    AddMarkerDecision,
    SetClipColorDecision,
    CreateSubclipDecision,
    AddToTimelineDecision,
]

DECISION_TYPE_MAP: dict[str, type[BaseModel]] = {
    "add_marker": AddMarkerDecision,
    "set_clip_color": SetClipColorDecision,
    "create_subclip": CreateSubclipDecision,
    "add_to_timeline": AddToTimelineDecision,
}


class DecisionEnvelope(BaseModel):
    """Top-level envelope wrapping a batch of edit decisions."""

    generated_by: str = Field(..., description="Tool/process that created this")
    generated_at: str = Field(..., description="ISO-8601 timestamp")
    fps: float = Field(..., gt=0, description="Timeline frame rate")
    decisions: list[dict[str, Any]] = Field(
        ..., min_length=1, description="List of decision objects"
    )


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def validate_decisions(data: dict[str, Any]) -> tuple[bool, list[str]]:
    """Validate a decisions envelope and all contained decisions.

    Returns:
        Tuple of (is_valid, list_of_error_messages).
        Empty error list when valid.
    """
    errors: list[str] = []

    # Validate envelope
    try:
        envelope = DecisionEnvelope(**data)
    except Exception as exc:
        errors.append(f"Envelope validation failed: {exc}")
        return False, errors

    # Validate each decision
    for idx, raw_decision in enumerate(envelope.decisions):
        dtype = raw_decision.get("type")
        if dtype is None:
            errors.append(f"Decision [{idx}]: missing 'type' field")
            continue
        model_cls = DECISION_TYPE_MAP.get(dtype)
        if model_cls is None:
            errors.append(
                f"Decision [{idx}]: unknown type '{dtype}'. "
                f"Valid types: {list(DECISION_TYPE_MAP.keys())}"
            )
            continue
        try:
            model_cls(**raw_decision)
        except Exception as exc:
            errors.append(f"Decision [{idx}] ({dtype}): {exc}")

    return len(errors) == 0, errors


# ---------------------------------------------------------------------------
# Executor context
# ---------------------------------------------------------------------------

class _ExecutionContext:
    """Holds Resolve connection objects and clip index for a batch run."""

    def __init__(self, resolve_connector: Any = None) -> None:
        self.resolve = resolve_connector
        self.project: Any = None
        self.timeline: Any = None
        self.media_pool: Any = None
        self.clip_index: dict[str, Any] = {}  # filename -> MediaPoolItem
        self.timeline_fps: Optional[float] = None

    def connect(self) -> None:
        """Establish Resolve connection and build clip index."""
        if self.resolve is None:
            from resolve_bridge import connect
            self.resolve = connect()

        pm = self.resolve.GetProjectManager()
        self.project = pm.GetCurrentProject()
        if self.project is None:
            raise RuntimeError("No project open in Resolve")

        self.timeline = self.project.GetCurrentTimeline()
        self.media_pool = self.project.GetMediaPool()

        # Read timeline FPS (confirmed working in Phase 2 live test)
        if self.timeline is not None:
            try:
                fps_val = self.timeline.GetSetting("timelineFrameRate")
                if fps_val:
                    self.timeline_fps = float(fps_val)
            except (TypeError, ValueError):
                pass

        # Build clip index: filename -> MediaPoolItem
        self._build_clip_index()

    def _build_clip_index(self) -> None:
        """Traverse media pool to map filenames to clip objects."""
        if self.media_pool is None:
            return
        root = self.media_pool.GetRootFolder()
        if root is None:
            return
        self._walk_folder(root)

    def _walk_folder(self, folder: Any) -> None:
        """Recursively walk a media pool folder and index clips by filename."""
        clips = folder.GetClipList()
        if clips:
            for clip in clips:
                file_path = clip.GetClipProperty("File Path")
                if file_path:
                    filename = Path(file_path).name
                    self.clip_index[filename] = clip

        subfolders = folder.GetSubFolderList()
        if subfolders:
            for sub in subfolders:
                self._walk_folder(sub)


# ---------------------------------------------------------------------------
# Decision handlers
# ---------------------------------------------------------------------------

def _handle_add_marker(
    decision: dict[str, Any], ctx: _ExecutionContext
) -> tuple[bool, str]:
    """Execute an add_marker decision against Resolve."""
    target = decision.get("marker_target", "timeline")

    if target == "timeline":
        if ctx.timeline is None:
            return False, "No active timeline in Resolve"
        ok = ctx.timeline.AddMarker(
            decision["frame_in"],
            decision["color"],
            decision["name"],
            decision.get("note", ""),
            decision.get("duration", 1),
        )
        if ok:
            return True, f"Added {decision['color']} marker '{decision['name']}' at frame {decision['frame_in']}"
        return False, f"AddMarker returned False for frame {decision['frame_in']}"

    # Clip marker
    filename = decision.get("entry_filename", "")
    clip = ctx.clip_index.get(filename)
    if clip is None:
        return False, f"Clip not found in media pool: {filename}"
    ok = clip.AddMarker(
        decision["frame_in"],
        decision["color"],
        decision["name"],
        decision.get("note", ""),
        decision.get("duration", 1),
    )
    if ok:
        return True, f"Added {decision['color']} clip marker '{decision['name']}' on {filename}"
    return False, f"AddMarker returned False for clip {filename}"


def _handle_set_clip_color(
    decision: dict[str, Any], ctx: _ExecutionContext
) -> tuple[bool, str]:
    """Execute a set_clip_color decision against Resolve."""
    filename = decision["entry_filename"]
    clip = ctx.clip_index.get(filename)
    if clip is None:
        return False, f"Clip not found in media pool: {filename}"
    ok = clip.SetClipColor(decision["color"])
    if ok:
        return True, f"Set color {decision['color']} on {filename}"
    return False, f"SetClipColor returned False for {filename}"


def _handle_create_subclip(
    decision: dict[str, Any], ctx: _ExecutionContext
) -> tuple[bool, str]:
    """Execute a create_subclip decision against Resolve.

    Note: Resolve API subclip support is Tier 3 (workaround needed).
    This handler sets mark in/out on the clip and creates a timeline from it.
    Live testing in Phase 2 will confirm the actual approach.
    """
    filename = decision["entry_filename"]
    clip = ctx.clip_index.get(filename)
    if clip is None:
        return False, f"Clip not found in media pool: {filename}"

    # Set in/out points on the media pool item
    clip.SetClipProperty("Start TC", str(decision["frame_in"]))
    clip.SetClipProperty("End TC", str(decision["frame_out"]))

    # Create a timeline from this clip (acts as a subclip)
    if ctx.media_pool is None:
        return False, "No media pool available"

    # Navigate to target bin if specified
    if decision.get("target_bin"):
        root = ctx.media_pool.GetRootFolder()
        target = None
        if root:
            for sub in (root.GetSubFolderList() or []):
                if sub.GetName() == decision["target_bin"]:
                    target = sub
                    break
            if target:
                ctx.media_pool.SetCurrentFolder(target)

    tl = ctx.media_pool.CreateTimelineFromClips(
        decision["subclip_name"], [clip]
    )
    if tl is None:
        return False, f"CreateTimelineFromClips failed for {decision['subclip_name']}"
    return True, f"Created subclip '{decision['subclip_name']}' from {filename}"


def _handle_add_to_timeline(
    decision: dict[str, Any], ctx: _ExecutionContext
) -> tuple[bool, str]:
    """Execute an add_to_timeline decision against Resolve."""
    filename = decision["entry_filename"]
    clip = ctx.clip_index.get(filename)
    if clip is None:
        return False, f"Clip not found in media pool: {filename}"

    if ctx.media_pool is None:
        return False, "No media pool available"

    # If a specific timeline is requested, switch to it
    target_tl_name = decision.get("target_timeline")
    if target_tl_name and ctx.project:
        for i in range(1, ctx.project.GetTimelineCount() + 1):
            tl = ctx.project.GetTimelineByIndex(i)
            if tl and tl.GetName() == target_tl_name:
                ctx.project.SetCurrentTimeline(tl)
                ctx.timeline = tl
                break

    result = ctx.media_pool.AppendToTimeline([{
        "mediaPoolItem": clip,
        "startFrame": decision["frame_in"],
        "endFrame": decision["frame_out"],
        "trackIndex": decision.get("track_index", 1),
    }])

    # AppendToTimeline returns a list: [PyRemoteObject] on success, [None] if
    # the clip is already present on the timeline or the append failed.
    if result and result[0] is not None:
        return True, f"Appended {filename} [{decision['frame_in']}-{decision['frame_out']}] to timeline"
    return False, f"AppendToTimeline failed for {filename} (clip may already be on timeline)"


# Handler registry
_HANDLERS: dict[str, Any] = {
    "add_marker": _handle_add_marker,
    "set_clip_color": _handle_set_clip_color,
    "create_subclip": _handle_create_subclip,
    "add_to_timeline": _handle_add_to_timeline,
}


# ---------------------------------------------------------------------------
# Executor
# ---------------------------------------------------------------------------

def execute_decisions(
    decisions_data: dict[str, Any],
    mode: str = "dry-run",
    resolve_connector: Any = None,
) -> dict[str, Any]:
    """Process an edit-decisions envelope against DaVinci Resolve.

    Args:
        decisions_data: Dict matching the DecisionEnvelope schema.
        mode: One of 'dry-run', 'confirm', 'execute'.
        resolve_connector: Injectable Resolve object for testing.

    Returns:
        Dict with: succeeded, failed, skipped, mode, details.
    """
    if mode not in EXECUTION_MODES:
        return {
            "succeeded": 0,
            "failed": 0,
            "skipped": 0,
            "mode": mode,
            "details": [{"index": -1, "type": "envelope", "status": "error",
                         "message": f"Invalid mode '{mode}'. Use: {EXECUTION_MODES}"}],
        }

    # Validate first
    valid, errors = validate_decisions(decisions_data)
    if not valid:
        return {
            "succeeded": 0,
            "failed": len(errors),
            "skipped": 0,
            "mode": mode,
            "details": [{"index": -1, "type": "validation", "status": "error",
                         "message": e} for e in errors],
        }

    raw_decisions = decisions_data.get("decisions", [])
    details: list[dict[str, Any]] = []
    succeeded = 0
    failed = 0
    skipped = 0

    # Dry-run and confirm: log actions without executing
    if mode in ("dry-run", "confirm"):
        for idx, raw in enumerate(raw_decisions):
            dtype = raw.get("type", "unknown")
            handler = _HANDLERS.get(dtype)
            if handler is None:
                details.append({
                    "index": idx, "type": dtype,
                    "status": "skipped", "message": f"Unknown decision type: {dtype}",
                })
                skipped += 1
            else:
                details.append({
                    "index": idx, "type": dtype,
                    "status": "planned", "message": _describe_decision(raw),
                })
                succeeded += 1

        return {
            "succeeded": succeeded,
            "failed": failed,
            "skipped": skipped,
            "mode": mode,
            "details": details,
        }

    # Execute mode — connect to Resolve and run handlers
    ctx = _ExecutionContext(resolve_connector)
    try:
        ctx.connect()
    except Exception as exc:
        return {
            "succeeded": 0,
            "failed": len(raw_decisions),
            "skipped": 0,
            "mode": mode,
            "details": [{"index": -1, "type": "connection", "status": "error",
                         "message": f"Resolve connection failed: {exc}"}],
        }

    for idx, raw in enumerate(raw_decisions):
        dtype = raw.get("type", "unknown")
        handler = _HANDLERS.get(dtype)

        if handler is None:
            details.append({
                "index": idx, "type": dtype,
                "status": "skipped", "message": f"Unknown decision type: {dtype}",
            })
            skipped += 1
            continue

        try:
            ok, msg = handler(raw, ctx)
            if ok:
                details.append({
                    "index": idx, "type": dtype,
                    "status": "succeeded", "message": msg,
                })
                succeeded += 1
            else:
                details.append({
                    "index": idx, "type": dtype,
                    "status": "failed", "message": msg,
                })
                failed += 1
        except Exception as exc:
            details.append({
                "index": idx, "type": dtype,
                "status": "failed", "message": f"Handler exception: {exc}",
            })
            failed += 1
            logger.warning("Decision [%d] (%s) raised: %s", idx, dtype, exc)

    return {
        "succeeded": succeeded,
        "failed": failed,
        "skipped": skipped,
        "mode": mode,
        "details": details,
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _describe_decision(raw: dict[str, Any]) -> str:
    """Human-readable description of a decision for dry-run output."""
    dtype = raw.get("type", "unknown")

    if dtype == "add_marker":
        target = raw.get("marker_target", "timeline")
        loc = f"on {raw.get('entry_filename', '?')}" if target == "clip" else "on timeline"
        return (
            f"Add {raw.get('color', '?')} marker '{raw.get('name', '?')}' "
            f"at frame {raw.get('frame_in', '?')} {loc}"
        )

    if dtype == "set_clip_color":
        return f"Set color {raw.get('color', '?')} on clip {raw.get('entry_filename', '?')}"

    if dtype == "create_subclip":
        return (
            f"Create subclip '{raw.get('subclip_name', '?')}' from "
            f"{raw.get('entry_filename', '?')} [{raw.get('frame_in', '?')}-{raw.get('frame_out', '?')}]"
        )

    if dtype == "add_to_timeline":
        return (
            f"Append {raw.get('entry_filename', '?')} "
            f"[{raw.get('frame_in', '?')}-{raw.get('frame_out', '?')}] to timeline"
        )

    return f"Unknown decision type: {dtype}"


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _cli() -> None:
    """Command-line entry point for resolve_decisions."""
    parser = argparse.ArgumentParser(
        description="Execute Resolve edit decisions from a JSON file."
    )
    parser.add_argument("input", help="Path to decisions JSON file")
    parser.add_argument(
        "--mode", choices=list(EXECUTION_MODES), default="dry-run",
        help="Execution mode (default: dry-run)",
    )
    parser.add_argument("--verbose", action="store_true", help="Verbose output")
    parser.add_argument("--output", help="Write results JSON to this path")
    args = parser.parse_args()

    if args.verbose:
        logging.basicConfig(level=logging.DEBUG)
    else:
        logging.basicConfig(level=logging.INFO)

    # Load input
    input_path = Path(args.input)
    if not input_path.exists():
        print(f"Error: file not found: {input_path}", file=sys.stderr)
        sys.exit(1)

    with open(input_path, encoding="utf-8") as f:
        data = json.load(f)

    # Execute
    results = execute_decisions(data, mode=args.mode)

    # Output
    if args.verbose or args.mode == "dry-run":
        print(json.dumps(results, indent=2))

    if args.output:
        out_path = Path(args.output)
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(results, f, indent=2)
        print(f"Results written to {out_path}")

    # Exit code
    if results["failed"] > 0:
        sys.exit(1)


if __name__ == "__main__":
    _cli()
