"""resolve_scope.py -- Session-scoped timeline builder for NB11 Resolve tools.

Every function requires explicit session or feed scope.
No function may operate on "all clips" or default to unscoped media pool.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path

from resolve_common import (
    STAGING_DIR,
    connect_resolve,
    find_or_create_bin,
    get_session_clips,
    list_all_sessions,
    read_session_manifest,
    read_sidecar,
    sync_strategy,
)


# ---------------------------------------------------------------------------
# 1. list_sessions
# ---------------------------------------------------------------------------

def list_sessions() -> None:
    """Print all sessions using list_all_sessions().

    Shows session_id, feed count, and feed types as a formatted table.
    """
    sessions = list_all_sessions()
    if not sessions:
        print("[INFO] No sessions found in staging.")
        return

    print(f"\n{'='*70}")
    print(f"  {'SESSION ID':<30} {'FEEDS':>5}  {'FEED TYPES'}")
    print(f"  {'-'*28}  {'-'*5}  {'-'*30}")
    for s in sessions:
        sid = s.get("session_id", "?")
        count = s.get("feed_count", 0)
        feeds = s.get("feed_list", [])
        # Extract unique feed types from feed names like "VRCAM-01"
        feed_types = sorted({f.split("-")[0] for f in feeds if "-" in f})
        types_str = ", ".join(feed_types) if feed_types else ", ".join(feeds)
        print(f"  {sid:<30} {count:>5}  {types_str}")
    print(f"{'='*70}\n")


# ---------------------------------------------------------------------------
# 2. get_session_feeds
# ---------------------------------------------------------------------------

def get_session_feeds(session_id: str) -> list[dict]:
    """Load all feed sidecar JSONs from STAGING_DIR/{session_id}/.

    Returns a list of parsed sidecar dicts. Excludes _session.json files.
    """
    session_dir = STAGING_DIR / session_id
    if not session_dir.is_dir():
        return []

    feeds: list[dict] = []
    for entry in sorted(session_dir.iterdir()):
        if entry.suffix == ".json" and not entry.name.endswith("_session.json"):
            feeds.append(read_sidecar(entry))
    return feeds


# ---------------------------------------------------------------------------
# 3. get_staged_files
# ---------------------------------------------------------------------------

def get_staged_files(session_id: str) -> list[str]:
    """Get paths to staged media files (non-.json files) in session dir.

    Returns a list of absolute file path strings.
    """
    session_dir = STAGING_DIR / session_id
    if not session_dir.is_dir():
        return []

    files: list[str] = []
    for entry in sorted(session_dir.iterdir()):
        if entry.is_file() and entry.suffix.lower() != ".json":
            files.append(str(entry))
    return files


# ---------------------------------------------------------------------------
# 4. build_timeline
# ---------------------------------------------------------------------------

def build_timeline(session_id: str, resolve=None) -> None:
    """Build a timeline from ONE session.

    MUST raise ValueError if session_id is empty or None.
    If resolve is None, does a dry run printing feeds.
    Otherwise: gets/imports clips from session bin, creates timeline
    named ``{session_id}_all`` in TIMELINES bin.
    """
    if not session_id:
        raise ValueError("session_id must not be empty or None")

    feeds = get_session_feeds(session_id)
    staged = get_staged_files(session_id)

    print(f"\n[BUILD] Timeline for session: {session_id}")
    print(f"  Feeds found: {len(feeds)}")
    print(f"  Staged files: {len(staged)}")

    if not feeds:
        print(f"  [WARN] No feeds found for session {session_id}")
        return

    for f in feeds:
        fid = f.get("feed_id", "?")
        ftype = f.get("feed_type", "?")
        dur = f.get("duration", 0.0)
        print(f"    {fid}  ({ftype}, {dur:.1f}s)")

    if resolve is None:
        print("  [DRY RUN] Skipping Resolve timeline creation.")
        return

    # --- Live Resolve path ---
    project = resolve.GetProjectManager().GetCurrentProject()
    if project is None:
        print("  [WARN] No open Resolve project. Cannot create timeline.")
        return

    media_pool = project.GetMediaPool()
    root = media_pool.GetRootFolder()

    # Get clips from session bin
    clips = get_session_clips(media_pool, session_id)
    if not clips:
        # Try importing staged files first
        raw_folder = find_or_create_bin(media_pool, root, "RAW FOOTAGE")
        session_folder = find_or_create_bin(media_pool, raw_folder, session_id)
        media_pool.SetCurrentFolder(session_folder)
        if staged:
            imported = media_pool.ImportMedia(staged)
            if imported:
                clips = imported
                print(f"  [OK] Imported {len(clips)} clip(s) from staging.")

    if not clips:
        print(f"  [WARN] No clips available for session {session_id}")
        return

    # Create timeline in TIMELINES bin
    timelines_bin = find_or_create_bin(media_pool, root, "TIMELINES")
    media_pool.SetCurrentFolder(timelines_bin)

    timeline_name = f"{session_id}_all"
    timeline = media_pool.CreateTimelineFromClips(timeline_name, clips)
    if timeline is None:
        # Fallback: create empty timeline and append
        timeline = media_pool.CreateEmptyTimeline(timeline_name)
        if timeline:
            media_pool.AppendToTimeline(clips)

    if timeline:
        print(f"  [OK] Timeline created: {timeline_name}")
    else:
        print(f"  [ERROR] Failed to create timeline: {timeline_name}")


# ---------------------------------------------------------------------------
# 5. build_feed_timeline
# ---------------------------------------------------------------------------

def build_feed_timeline(feed_id: str, resolve=None) -> None:
    """Build a timeline from a single feed.

    Extracts session_id from feed_id (everything before last ``_TYPE-N``).
    Finds the feed sidecar, finds the staged file, creates timeline.
    """
    if not feed_id:
        raise ValueError("feed_id must not be empty or None")

    # Parse session_id from feed_id: e.g. "KEYNOTE_20250220_001_VRCAM-03"
    # Session is everything before the last _TYPE-NN segment
    parts = feed_id.rsplit("_", 1)
    if len(parts) < 2:
        raise ValueError(f"Cannot parse session_id from feed_id: {feed_id}")
    session_id = parts[0]

    print(f"\n[BUILD] Feed timeline for: {feed_id}")
    print(f"  Session: {session_id}")

    # Find the sidecar
    sidecar_path = STAGING_DIR / session_id / f"{feed_id}.json"
    if not sidecar_path.exists():
        print(f"  [ERROR] Sidecar not found: {sidecar_path}")
        return

    sidecar = read_sidecar(sidecar_path)
    source_path = sidecar.get("source_path", "")
    ftype = sidecar.get("feed_type", "?")
    dur = sidecar.get("duration", 0.0)
    print(f"  Feed type: {ftype}, Duration: {dur:.1f}s")
    print(f"  Source: {source_path}")

    if resolve is None:
        print("  [DRY RUN] Skipping Resolve timeline creation.")
        return

    # --- Live Resolve path ---
    project = resolve.GetProjectManager().GetCurrentProject()
    if project is None:
        print("  [WARN] No open Resolve project. Cannot create timeline.")
        return

    media_pool = project.GetMediaPool()
    root = media_pool.GetRootFolder()

    # Import the single feed file
    raw_folder = find_or_create_bin(media_pool, root, "RAW FOOTAGE")
    session_folder = find_or_create_bin(media_pool, raw_folder, session_id)
    media_pool.SetCurrentFolder(session_folder)

    clips = []
    if source_path and os.path.isfile(source_path):
        imported = media_pool.ImportMedia([source_path])
        if imported:
            clips = imported

    if not clips:
        # Try to find existing clip in session bin
        all_clips = get_session_clips(media_pool, session_id)
        for c in all_clips:
            if feed_id in (c.GetName() or ""):
                clips = [c]
                break

    if not clips:
        print(f"  [WARN] No clips found for feed {feed_id}")
        return

    # Create timeline
    timelines_bin = find_or_create_bin(media_pool, root, "TIMELINES")
    media_pool.SetCurrentFolder(timelines_bin)

    timeline_name = feed_id
    timeline = media_pool.CreateTimelineFromClips(timeline_name, clips)
    if timeline is None:
        timeline = media_pool.CreateEmptyTimeline(timeline_name)
        if timeline:
            media_pool.AppendToTimeline(clips)

    if timeline:
        print(f"  [OK] Timeline created: {timeline_name}")
    else:
        print(f"  [ERROR] Failed to create timeline: {timeline_name}")


# ---------------------------------------------------------------------------
# 6. build_multi_timeline
# ---------------------------------------------------------------------------

def build_multi_timeline(
    session_ids: list[str],
    name: str,
    resolve=None,
) -> None:
    """Cross-session combine timeline.

    MUST raise ValueError if name is empty.
    Creates an empty timeline, appends clips from each session.
    Adds Orange boundary marker at session transitions with note
    identifying sessions.
    """
    if not name:
        raise ValueError("name must not be empty for multi-timeline")

    if not session_ids:
        raise ValueError("session_ids must not be empty")

    print(f"\n[COMBINE] Multi-session timeline: {name}")
    print(f"  Sessions: {', '.join(session_ids)}")

    # Dry run: print what would happen
    for sid in session_ids:
        feeds = get_session_feeds(sid)
        staged = get_staged_files(sid)
        print(f"  {sid}: {len(feeds)} feed(s), {len(staged)} staged file(s)")

    if resolve is None:
        print("  [DRY RUN] Skipping Resolve timeline creation.")
        return

    # --- Live Resolve path ---
    project = resolve.GetProjectManager().GetCurrentProject()
    if project is None:
        print("  [WARN] No open Resolve project. Cannot create timeline.")
        return

    media_pool = project.GetMediaPool()
    root = media_pool.GetRootFolder()

    # Create empty timeline in TIMELINES bin
    timelines_bin = find_or_create_bin(media_pool, root, "TIMELINES")
    media_pool.SetCurrentFolder(timelines_bin)

    timeline = media_pool.CreateEmptyTimeline(name)
    if timeline is None:
        print(f"  [ERROR] Failed to create timeline: {name}")
        return

    project.SetCurrentTimeline(timeline)

    # Append clips from each session with boundary markers
    prev_session = None
    for sid in session_ids:
        clips = get_session_clips(media_pool, sid)
        if not clips:
            print(f"  [WARN] No clips for session {sid}, skipping.")
            continue

        # Add Orange boundary marker at session transitions
        if prev_session is not None:
            # Get current timeline length for marker position
            tl = project.GetCurrentTimeline()
            if tl:
                frame_count = tl.GetEndFrame()
                marker_note = f"Session boundary: {prev_session} -> {sid}"
                tl.AddMarker(
                    frame_count,      # frame position
                    "Orange",         # color
                    "SESSION BOUNDARY",  # name
                    marker_note,      # note
                    1,                # duration (frames)
                )

        media_pool.AppendToTimeline(clips)
        print(f"  [OK] Appended {len(clips)} clip(s) from {sid}")
        prev_session = sid

    print(f"  [OK] Multi-session timeline created: {name}")


# ---------------------------------------------------------------------------
# 7. main (argparse CLI)
# ---------------------------------------------------------------------------

def main() -> None:
    """CLI entry point with mutually exclusive modes."""
    parser = argparse.ArgumentParser(
        description="resolve_scope -- Session-scoped timeline builder for NB11 Resolve tools.",
    )

    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--list", action="store_true", help="List all sessions with feed info")
    mode.add_argument("--build", type=str, metavar="SESSION_ID", help="Build timeline from one session")
    mode.add_argument("--build-feed", type=str, metavar="FEED_ID", help="Build timeline from a single feed")
    mode.add_argument("--combine", nargs="+", metavar="SESSION_ID", help="Combine multiple sessions into one timeline")

    parser.add_argument("--name", type=str, metavar="TEXT", help="Timeline name (required for --combine)")
    parser.add_argument("--no-resolve", action="store_true", help="Skip DaVinci Resolve connection (dry run)")

    args = parser.parse_args()

    # Resolve connection
    resolve = None
    if not args.no_resolve and not args.list:
        try:
            resolve = connect_resolve()
        except SystemExit:
            print("[WARN] Proceeding without Resolve (dry run).")
            resolve = None

    # --list mode
    if args.list:
        list_sessions()
        return

    # --build mode
    if args.build:
        build_timeline(args.build, resolve=resolve)
        return

    # --build-feed mode
    if args.build_feed:
        build_feed_timeline(args.build_feed, resolve=resolve)
        return

    # --combine mode
    if args.combine:
        if not args.name:
            parser.error("--name TEXT is required for --combine")
        build_multi_timeline(args.combine, name=args.name, resolve=resolve)
        return


if __name__ == "__main__":
    main()
