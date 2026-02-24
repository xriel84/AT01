"""resolve_ingest.py -- Validated ingest pipeline for NB11 Resolve tools.

Scans INGEST_DIR subdirs, validates media files, generates IDs, stages files
with sidecar JSON, archives originals, and optionally imports to Resolve.
"""

from __future__ import annotations

import argparse
import os
import shutil
import time
from datetime import datetime
from pathlib import Path

from resolve_common import (
    ARCHIVE_DIR,
    CLIP_COLORS,
    FEED_SUBDIRS,
    FEED_TYPE_MAP,
    INGEST_DIR,
    STAGING_DIR,
    SUPPORTED_AUDIO_EXTS,
    SUPPORTED_VIDEO_EXTS,
    FeedID,
    SessionID,
    connect_resolve,
    deterministic_feed_hash,
    ensure_dirs,
    find_or_create_bin,
    get_file_creation_date,
    list_all_sessions,
    next_session_seq,
    register_session,
    remux_mkv_to_mp4,
    validate_video,
    write_session_manifest,
    write_sidecar,
)


# ---------------------------------------------------------------------------
# 1. scan_ingest_dir
# ---------------------------------------------------------------------------

def scan_ingest_dir(base_dir: str | None = None) -> dict[str, list[str]]:
    """Scan *base_dir* (default INGEST_DIR) subdirectories for media files.

    Only processes subdirectories whose names are in FEED_SUBDIRS.
    Maps subdir names to feed types via FEED_TYPE_MAP.
    Only includes files with supported video/audio extensions.

    Returns a dict mapping feed type (e.g. "VRCAM") to a list of absolute
    file paths.
    """
    root = Path(base_dir) if base_dir else INGEST_DIR
    all_supported = SUPPORTED_VIDEO_EXTS | SUPPORTED_AUDIO_EXTS
    result: dict[str, list[str]] = {}

    for subdir_name in FEED_SUBDIRS:
        subdir = root / subdir_name
        if not subdir.is_dir():
            continue

        feed_type = FEED_TYPE_MAP.get(subdir_name)
        if feed_type is None:
            continue

        files: list[str] = []
        for entry in subdir.iterdir():
            if entry.is_file() and entry.suffix.lower() in all_supported:
                files.append(str(entry))

        if files:
            result[feed_type] = files

    return result


# ---------------------------------------------------------------------------
# 2. build_feed_sidecar
# ---------------------------------------------------------------------------

def build_feed_sidecar(
    feed_id: str,
    session_id: str,
    feed_type: str,
    source_path: str,
    original_filename: str,
    creation_date: str,
    validation: dict,
) -> dict:
    """Build a sidecar metadata dict for a single feed file.

    The *validation* dict is expected to contain keys like duration, codec,
    fps, validation_status, and either 'resolution' (str) or 'width'/'height'
    (int).  Returns a flat dict suitable for JSON serialisation.
    """
    # Determine resolution string
    if "width" in validation and "height" in validation and validation["width"] and validation["height"]:
        resolution = f"{validation['width']}x{validation['height']}"
    else:
        resolution = validation.get("resolution", "")

    return {
        "feed_id": feed_id,
        "session_id": session_id,
        "feed_type": feed_type,
        "source_path": source_path,
        "original_filename": original_filename,
        "creation_date": creation_date,
        "duration": validation.get("duration", 0.0),
        "codec": validation.get("codec", ""),
        "resolution": resolution,
        "fps": validation.get("fps", 0.0),
        "validation_status": validation.get("validation_status", ""),
        "ingest_timestamp": datetime.now().isoformat(),
    }


# ---------------------------------------------------------------------------
# 3. build_session_manifest
# ---------------------------------------------------------------------------

def build_session_manifest(
    session_id: str,
    human_name: str,
    feeds: list[str],
) -> dict:
    """Build a session manifest dict.

    Returns a dict with session metadata including feed_count and sync stubs.
    """
    return {
        "session_id": session_id,
        "human_name": human_name,
        "feed_count": len(feeds),
        "feed_list": feeds,
        "sync_method": "TBD",
        "sync_offset_stub": None,
    }


# ---------------------------------------------------------------------------
# 4. process_file
# ---------------------------------------------------------------------------

def process_file(
    file_path: str,
    feed_type: str,
    session: SessionID,
    feed_counters: dict[str, int],
    resolve=None,
) -> dict | None:
    """Validate, optionally remux, stage, sidecar, and archive a single file.

    *feed_counters* is a mutable dict tracking the next index per feed_type.
    Returns the sidecar dict on success, or None if the file is skipped.
    """
    filename = os.path.basename(file_path)
    ext = os.path.splitext(filename)[1].lower()

    print(f"  Processing: {filename}")

    # Validate
    validation = validate_video(file_path)
    status = validation.get("validation_status", "")

    if status.startswith("rejected"):
        print(f"    SKIPPED ({status}): {validation.get('error', '')}")
        return None

    # Determine feed index
    idx = feed_counters.get(feed_type, 1)
    feed_counters[feed_type] = idx + 1

    feed_id_obj = FeedID(session=session, feed_type=feed_type, index=idx)
    feed_id_str = str(feed_id_obj)

    # Build staging path
    session_str = str(session)
    session_staging = Path(STAGING_DIR) / session_str
    session_staging.mkdir(parents=True, exist_ok=True)

    # Remux MKV if needed
    if validation.get("needs_remux", False):
        staged_name = f"{feed_id_str}.mp4"
        staged_path = session_staging / staged_name
        print(f"    Remuxing MKV -> MP4...")
        success = remux_mkv_to_mp4(file_path, str(staged_path))
        if not success:
            print(f"    SKIPPED: Remux failed for {filename}")
            return None
    else:
        staged_name = f"{feed_id_str}{ext}"
        staged_path = session_staging / staged_name
        shutil.copy2(file_path, staged_path)

    print(f"    Staged: {staged_name}")

    # Build and write sidecar
    creation_date = get_file_creation_date(file_path)
    sidecar = build_feed_sidecar(
        feed_id=feed_id_str,
        session_id=session_str,
        feed_type=feed_type,
        source_path=str(staged_path),
        original_filename=filename,
        creation_date=creation_date,
        validation=validation,
    )

    sidecar_path = session_staging / f"{feed_id_str}.json"
    write_sidecar(str(sidecar_path), sidecar)
    print(f"    Sidecar: {sidecar_path.name}")

    # Archive original
    session_archive = Path(ARCHIVE_DIR) / session_str
    session_archive.mkdir(parents=True, exist_ok=True)
    archive_dest = session_archive / filename
    shutil.copy2(file_path, archive_dest)
    print(f"    Archived: {archive_dest}")

    return sidecar


# ---------------------------------------------------------------------------
# 5. import_to_resolve
# ---------------------------------------------------------------------------

def import_to_resolve(resolve, session_id: str, staged_files: list[str]) -> None:
    """Import staged files into Resolve media pool under RAW FOOTAGE/{session_id}.

    Sets clip color to Blue (unreviewed). Skips entirely if *resolve* is None.
    """
    if resolve is None:
        print("[INFO] Resolve import skipped (--no-resolve)")
        return

    if not staged_files:
        print("[INFO] No files to import to Resolve.")
        return

    project = resolve.GetProjectManager().GetCurrentProject()
    if project is None:
        print("[WARN] No open Resolve project. Skipping import.")
        return

    media_pool = project.GetMediaPool()
    root = media_pool.GetRootFolder()

    # Navigate to RAW FOOTAGE / session_id
    raw_folder = find_or_create_bin(media_pool, root, "RAW FOOTAGE")
    session_folder = find_or_create_bin(media_pool, raw_folder, session_id)

    media_pool.SetCurrentFolder(session_folder)

    imported = media_pool.ImportMedia(staged_files)
    if not imported:
        print("[WARN] Resolve ImportMedia returned empty. Check file compatibility.")
        return

    # Set clip color to Blue
    blue = CLIP_COLORS["unreviewed"]
    for clip in imported:
        clip.SetClipColor(blue)

    print(f"[OK] Imported {len(imported)} clip(s) to RAW FOOTAGE/{session_id} (Blue)")


# ---------------------------------------------------------------------------
# 6. ingest_batch
# ---------------------------------------------------------------------------

def ingest_batch(
    files_by_type: dict[str, list[str]],
    session_name: str,
    resolve=None,
) -> None:
    """Process a batch of files grouped by feed type.

    Creates a SessionID, processes every file, writes a session manifest,
    imports to Resolve, and prints a summary.
    """
    if not files_by_type:
        print("[INFO] No files to ingest.")
        return

    # Determine creation date from the first file found
    first_file = None
    for flist in files_by_type.values():
        if flist:
            first_file = flist[0]
            break

    if first_file is None:
        print("[INFO] No files to ingest.")
        return

    creation_date = get_file_creation_date(first_file)
    human_name = session_name.upper()

    # Get next sequence number and build SessionID
    seq = next_session_seq(human_name, creation_date)
    session = SessionID(human_name=human_name, date=creation_date, seq=seq)
    session_str = str(session)

    print(f"\n{'='*60}")
    print(f"  INGEST SESSION: {session_str}")
    print(f"{'='*60}")

    # Register the session
    register_session(session)

    # Process all files
    feed_counters: dict[str, int] = {}
    all_sidecars: list[dict] = []
    staged_files: list[str] = []
    feed_names: list[str] = []

    for feed_type, file_list in sorted(files_by_type.items()):
        print(f"\n  --- {feed_type} ({len(file_list)} file(s)) ---")
        feed_counters.setdefault(feed_type, 1)

        for fpath in sorted(file_list):
            sidecar = process_file(fpath, feed_type, session, feed_counters, resolve)
            if sidecar is not None:
                all_sidecars.append(sidecar)
                staged_files.append(sidecar["source_path"])
                feed_names.append(sidecar["feed_id"].split("_")[-1])  # e.g. VRCAM-01

    # Write session manifest
    session_staging = Path(STAGING_DIR) / session_str
    session_staging.mkdir(parents=True, exist_ok=True)

    manifest = build_session_manifest(
        session_id=session_str,
        human_name=human_name,
        feeds=feed_names,
    )
    manifest_path = session_staging / "_session.json"
    write_session_manifest(str(manifest_path), manifest)
    print(f"\n  Session manifest: {manifest_path}")

    # Import to Resolve
    import_to_resolve(resolve, session_str, staged_files)

    # Summary
    print(f"\n{'='*60}")
    print(f"  SUMMARY: {session_str}")
    print(f"  Files processed: {len(all_sidecars)}")
    print(f"  Feeds: {', '.join(feed_names) if feed_names else 'none'}")
    print(f"  Staging: {session_staging}")
    print(f"{'='*60}\n")


# ---------------------------------------------------------------------------
# 7. watch_mode
# ---------------------------------------------------------------------------

def watch_mode(session_name: str, resolve=None) -> None:
    """Poll INGEST_DIR every 1 second. Batch when 30 seconds elapse with no
    new files. Ctrl+C to stop.
    """
    print(f"[WATCH] Monitoring {INGEST_DIR} ...")
    print("[WATCH] Files will batch after 30s of no new arrivals. Ctrl+C to stop.\n")

    ensure_dirs()
    last_seen: set[str] = set()
    last_change_time: float = 0.0
    pending: dict[str, list[str]] = {}

    try:
        while True:
            current = scan_ingest_dir()
            current_files: set[str] = set()
            for flist in current.values():
                current_files.update(flist)

            new_files = current_files - last_seen
            if new_files:
                last_change_time = time.time()
                last_seen = current_files
                pending = current
                for f in sorted(new_files):
                    print(f"  [NEW] {os.path.basename(f)}")

            # Batch trigger: 30s since last new file, and we have pending files
            if pending and last_change_time > 0:
                elapsed = time.time() - last_change_time
                if elapsed >= 30.0:
                    print(f"\n[WATCH] 30s gap detected. Starting batch ingest...")
                    ingest_batch(pending, session_name, resolve)
                    pending = {}
                    last_seen = set()  # Reset so re-scans pick up any new arrivals
                    last_change_time = 0.0

            time.sleep(1.0)

    except KeyboardInterrupt:
        print("\n[WATCH] Stopped by user.")
        if pending:
            print("[WATCH] Flushing remaining files...")
            ingest_batch(pending, session_name, resolve)


# ---------------------------------------------------------------------------
# 8. cmd_list
# ---------------------------------------------------------------------------

def cmd_list() -> None:
    """Print all registered sessions."""
    sessions = list_all_sessions()
    if not sessions:
        print("[INFO] No sessions found.")
        return

    print(f"\n{'='*60}")
    print(f"  SESSIONS ({len(sessions)})")
    print(f"{'='*60}")
    for s in sessions:
        sid = s.get("session_id", "?")
        name = s.get("human_name", "?")
        count = s.get("feed_count", 0)
        feeds = s.get("feed_list", [])
        print(f"  {sid}  ({name}, {count} feeds: {', '.join(feeds)})")
    print()


# ---------------------------------------------------------------------------
# 9. main (argparse CLI)
# ---------------------------------------------------------------------------

def main() -> None:
    """CLI entry point with mutually exclusive modes."""
    parser = argparse.ArgumentParser(
        description="resolve_ingest -- Validated ingest pipeline for NB11 Resolve tools.",
    )

    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--watch", action="store_true", help="Watch mode: poll INGEST_DIR, batch on 30s gap")
    mode.add_argument("--once", action="store_true", help="One-shot mode: ingest current files and exit")
    mode.add_argument("--file", type=str, metavar="PATH", help="Single-file mode: ingest one file")
    mode.add_argument("--list", action="store_true", help="List all registered sessions")

    parser.add_argument("--session", type=str, metavar="NAME", help="Session name (required for ingest operations)")
    parser.add_argument("--no-resolve", action="store_true", help="Skip DaVinci Resolve import")

    args = parser.parse_args()

    # Resolve connection
    resolve = None
    needs_resolve = not args.no_resolve and not args.list

    if needs_resolve:
        try:
            resolve = connect_resolve()
        except SystemExit:
            print("[WARN] Proceeding without Resolve.")
            resolve = None

    # Ensure directories exist for ingest operations
    if not args.list:
        ensure_dirs()

    # --list mode
    if args.list:
        cmd_list()
        return

    # Validate --session is provided for ingest modes
    if not args.session:
        parser.error("--session NAME is required for ingest operations (--watch, --once, --file)")

    # --file mode
    if args.file:
        fpath = os.path.abspath(args.file)
        if not os.path.isfile(fpath):
            print(f"[ERROR] File not found: {fpath}")
            return

        # Determine feed type from parent dir name
        parent_name = os.path.basename(os.path.dirname(fpath)).lower()
        feed_type = FEED_TYPE_MAP.get(parent_name, "VRCAM")  # default to VRCAM

        files_by_type = {feed_type: [fpath]}
        ingest_batch(files_by_type, args.session, resolve)
        return

    # --once mode
    if args.once:
        files_by_type = scan_ingest_dir()
        ingest_batch(files_by_type, args.session, resolve)
        return

    # --watch mode
    if args.watch:
        watch_mode(args.session, resolve)
        return


if __name__ == "__main__":
    main()
