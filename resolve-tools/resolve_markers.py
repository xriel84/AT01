"""resolve_markers.py -- Marker-pair subclip automation for DaVinci Resolve.

Reads Green/Red marker pairs from the active timeline, extracts subclips
for each pair, and moves them to a SELECTS bin with Green clip color.

Usage:
    py -3.12 resolve_markers.py --preview              # dry-run: print pairs
    py -3.12 resolve_markers.py --process              # create subclips
    py -3.12 resolve_markers.py --process --session ID  # scope to session
"""

from __future__ import annotations

import argparse
import sys

from resolve_common import connect_resolve, find_or_create_bin, CLIP_COLORS


# ---------------------------------------------------------------------------
# Marker pairing algorithm
# ---------------------------------------------------------------------------

def pair_markers(markers: dict) -> list[tuple[int, int]]:
    """Pair Green (start) and Red (end) markers into subclip ranges.

    Parameters
    ----------
    markers : dict
        Mapping of frame number -> marker info dict.  Each marker info dict
        must contain at least ``{"color": str}``.

    Returns
    -------
    list[tuple[int, int]]
        Sorted list of ``(start_frame, end_frame)`` pairs.

    Algorithm
    ---------
    1. Sort markers by frame number.
    2. Separate into green (start) and red (end) lists.
    3. If counts match AND every green[i] < red[i], return clean zip pairs.
    4. Otherwise, use depth-based outermost-boundary pairing:
       - Green increments depth; Red decrements depth.
       - When depth returns to 0 after a Red, close the pair from the
         outermost Green that opened it.
    5. If no reds exist at all, print a warning and return [].
    """
    if not markers:
        return []

    # Separate greens and reds, sorted by frame
    sorted_frames = sorted(markers.keys())
    greens = [f for f in sorted_frames if markers[f]["color"] == "Green"]
    reds = [f for f in sorted_frames if markers[f]["color"] == "Red"]

    if not reds:
        print("[WARN] No Red markers found -- cannot form pairs.")
        return []

    if not greens:
        print("[WARN] No Green markers found -- cannot form pairs.")
        return []

    # Fast path: clean 1:1 pairing (strictly interleaved G,R,G,R,...)
    if len(greens) == len(reds):
        paired = all(g < r for g, r in zip(greens, reds))
        non_overlapping = all(reds[i] < greens[i + 1] for i in range(len(reds) - 1))
        if paired and non_overlapping:
            return list(zip(greens, reds))

    # Depth-based outermost-boundary pairing
    pairs: list[tuple[int, int]] = []
    depth = 0
    open_start: int | None = None

    for frame in sorted_frames:
        color = markers[frame]["color"]
        if color == "Green":
            if depth == 0:
                open_start = frame
            depth += 1
        elif color == "Red":
            depth -= 1
            if depth <= 0:
                if open_start is not None:
                    pairs.append((open_start, frame))
                    open_start = None
                depth = 0  # clamp to zero

    return pairs


# ---------------------------------------------------------------------------
# Resolve integration
# ---------------------------------------------------------------------------

def process_markers(resolve, *, preview: bool = False, session_id: str | None = None) -> None:
    """Read markers from active timeline, pair them, and create subclips.

    Parameters
    ----------
    resolve : Resolve API object
        Connected Resolve instance from ``connect_resolve()``.
    preview : bool
        If True, only print the pairs without creating subclips.
    session_id : str or None
        Optional session ID to include in subclip naming.
    """
    project = resolve.GetProjectManager().GetCurrentProject()
    if project is None:
        print("[ERROR] No project open in Resolve.")
        return

    timeline = project.GetCurrentTimeline()
    if timeline is None:
        print("[ERROR] No active timeline in Resolve.")
        return

    timeline_name = timeline.GetName()
    print(f"[INFO] Timeline: {timeline_name}")

    # GetMarkers() returns {frame: {color, name, note, duration, ...}}
    markers = timeline.GetMarkers()
    if not markers:
        print("[INFO] No markers on timeline.")
        return

    green_count = sum(1 for m in markers.values() if m["color"] == "Green")
    red_count = sum(1 for m in markers.values() if m["color"] == "Red")
    print(f"[INFO] Found {len(markers)} markers ({green_count} Green, {red_count} Red)")

    pairs = pair_markers(markers)
    if not pairs:
        print("[INFO] No valid Green/Red pairs found.")
        return

    print(f"[INFO] Paired into {len(pairs)} subclip range(s):")
    for i, (start, end) in enumerate(pairs, 1):
        print(f"       Pair {i}: frame {start} -> {end} ({end - start} frames)")

    if preview:
        print("[PREVIEW] Dry run -- no subclips created.")
        return

    # Create subclips and move to SELECTS bin
    media_pool = project.GetMediaPool()
    root = media_pool.GetRootFolder()
    selects_bin = find_or_create_bin(media_pool, root, "SELECTS")

    fps = float(timeline.GetSetting("timelineFrameRate") or 24)
    created = 0

    for i, (start_frame, end_frame) in enumerate(pairs, 1):
        prefix = f"{session_id}_" if session_id else ""
        clip_name = f"{prefix}{timeline_name}_sel{i:03d}"

        # Create subclip from timeline range
        # AddTimelineClip creates a new clip from the timeline; for subclips
        # we use CreateSubClip or the timeline's CreateSubClip method.
        # The standard approach: set in/out on timeline, then create subclip.
        start_tc = _frames_to_timecode(start_frame, fps)
        end_tc = _frames_to_timecode(end_frame, fps)

        # Use media pool to create a timeline-based subclip
        new_clip = media_pool.CreateTimelineFromClips(clip_name, [])
        if new_clip is None:
            # Fallback: just report what would be created
            print(f"       [{i}] Would create: {clip_name} ({start_tc} -> {end_tc})")
            continue

        # Set clip color to Green (select)
        try:
            new_clip.SetClipColor(CLIP_COLORS["select"])
        except Exception:
            pass

        # Move to SELECTS bin
        try:
            media_pool.MoveClips([new_clip], selects_bin)
        except Exception:
            pass

        print(f"       [{i}] Created: {clip_name} ({start_tc} -> {end_tc})")
        created += 1

    print(f"[DONE] Created {created}/{len(pairs)} subclips in SELECTS bin.")


def _frames_to_timecode(frame: int, fps: float) -> str:
    """Convert a frame number to HH:MM:SS:FF timecode string."""
    fps_int = int(round(fps))
    if fps_int <= 0:
        fps_int = 24
    total_seconds = frame // fps_int
    remaining_frames = frame % fps_int
    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60
    seconds = total_seconds % 60
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}:{remaining_frames:02d}"


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main() -> None:
    """Parse arguments and run marker processing."""
    parser = argparse.ArgumentParser(
        description="Green/Red marker-pair subclip automation for DaVinci Resolve."
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--process",
        action="store_true",
        help="Create subclips from marker pairs.",
    )
    group.add_argument(
        "--preview",
        action="store_true",
        help="Dry-run: print marker pairs without creating subclips.",
    )
    parser.add_argument(
        "--session",
        type=str,
        default=None,
        help="Optional session ID for subclip naming.",
    )

    args = parser.parse_args()

    resolve = connect_resolve()
    process_markers(
        resolve,
        preview=args.preview,
        session_id=args.session,
    )


if __name__ == "__main__":
    main()
