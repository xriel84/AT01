"""resolve_deliver.py -- Render automation and delivery manifest generation.

Dispatches Resolve renders per platform preset and produces a delivery
manifest with social metadata placeholders, analytics hooks, and a
feedback-loop skeleton for downstream review/iteration.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from resolve_common import (
    DELIVERY_DIR,
    STAGING_DIR,
    connect_resolve,
    read_session_manifest,
    list_all_sessions,
    write_sidecar,
)
from resolve_template import RENDER_PRESETS


# ---------------------------------------------------------------------------
# Platform -> render-preset mapping
# ---------------------------------------------------------------------------

PLATFORM_MAP: dict[str, str] = {
    "youtube": "YouTube 16:9",
    "tiktok": "TikTok 9:16",
    "instagram": "IG Square 1:1",
    "archive": "Archive",
    "thumbnails": "Thumbnail",
}


# ---------------------------------------------------------------------------
# Builder functions (pure data, no Resolve dependency)
# ---------------------------------------------------------------------------

def build_deliverable_entry(
    platform: str,
    filename: str,
    resolution: str,
    duration_sec: float,
    file_size_bytes: int,
    codec: str,
    render_preset: str,
) -> dict:
    """Return a flat dict describing a single rendered deliverable."""
    return {
        "platform": platform,
        "filename": filename,
        "resolution": resolution,
        "duration_sec": duration_sec,
        "file_size_bytes": file_size_bytes,
        "codec": codec,
        "render_preset": render_preset,
    }


def build_manifest(
    session_id: str,
    timeline_name: str,
    duration_sec: float,
    feeds_used: list[str],
    deliverables: list[dict],
) -> dict:
    """Return a full delivery manifest dict.

    Includes social_metadata with PLACEHOLDER strings, analytics_hooks,
    and a feedback_loop skeleton.
    """
    now = datetime.now(timezone.utc)
    iso_now = now.isoformat()
    timestamp = now.strftime("%Y%m%d%H%M%S")

    return {
        "session_id": session_id,
        "generated_at": iso_now,
        "source_timeline": timeline_name,
        "total_duration_sec": duration_sec,
        "feeds_used": feeds_used,
        "deliverables": deliverables,
        "social_metadata": {
            "title": "PLACEHOLDER -- set title before publish",
            "description": "PLACEHOLDER -- set description before publish",
            "tags": [],
            "category": "PLACEHOLDER",
            "scheduled_publish": None,
            "series_name": None,
            "episode_number": None,
        },
        "analytics_hooks": {
            "tracking_id": f"{session_id}_{timestamp}",
            "utm_source": "PLACEHOLDER",
            "utm_medium": "PLACEHOLDER",
            "utm_campaign": "PLACEHOLDER",
            "performance_log_path": str(
                DELIVERY_DIR / session_id / "analytics.json"
            ),
        },
        "feedback_loop": {
            "status": "pending_review",
            "reviewer": None,
            "review_notes": None,
            "performance_data": None,
            "iteration_of": None,
            "superseded_by": None,
        },
    }


def build_analytics(session_id: str) -> dict:
    """Return an empty analytics scaffold for *session_id*."""
    return {
        "session_id": session_id,
        "platform_results": [],
        "comparison_to_previous": None,
        "recommended_adjustments": None,
    }


# ---------------------------------------------------------------------------
# Render workflow (requires live Resolve)
# ---------------------------------------------------------------------------

def render_session(
    session_id: str,
    platforms: list[str] | None = None,
    resolve=None,
) -> dict:
    """Full render workflow using the Resolve API.

    For each platform in *platforms* (defaults to all PLATFORM_MAP keys),
    applies the corresponding RENDER_PRESETS settings, adds a render job,
    renders, and records the deliverable.

    Returns the delivery manifest dict.
    """
    if platforms is None:
        platforms = list(PLATFORM_MAP.keys())

    if resolve is None:
        resolve = connect_resolve()

    pm = resolve.GetProjectManager()
    project = pm.GetCurrentProject()
    if project is None:
        print("[ERROR] No project open in Resolve.")
        sys.exit(1)

    timeline = project.GetCurrentTimeline()
    if timeline is None:
        print("[ERROR] No timeline selected in Resolve.")
        sys.exit(1)

    timeline_name = timeline.GetName()
    fps = float(timeline.GetSetting("timelineFrameRate") or 24)
    total_frames = timeline.GetEndFrame() - timeline.GetStartFrame()
    duration_sec = total_frames / fps if fps > 0 else 0.0

    # Collect feeds from timeline clips
    feeds_used: list[str] = []
    for track_idx in range(1, timeline.GetTrackCount("video") + 1):
        for clip in (timeline.GetItemListInTrack("video", track_idx) or []):
            clip_name = clip.GetName()
            if clip_name and clip_name not in feeds_used:
                feeds_used.append(clip_name)

    # Create output directory
    output_dir = DELIVERY_DIR / session_id
    output_dir.mkdir(parents=True, exist_ok=True)

    deliverables: list[dict] = []

    for platform in platforms:
        preset_name = PLATFORM_MAP.get(platform)
        if preset_name is None:
            print(f"[WARN] Unknown platform '{platform}', skipping.")
            continue

        preset = RENDER_PRESETS.get(preset_name)
        if preset is None:
            print(f"[WARN] No render preset '{preset_name}', skipping.")
            continue

        print(f"\n[RENDER] {platform} -> {preset_name}")

        # Build render settings
        settings: dict = {
            "TargetDir": str(output_dir),
            "CustomName": f"{session_id}_{platform}",
        }
        if preset.get("width"):
            settings["FormatWidth"] = preset["width"]
        if preset.get("height"):
            settings["FormatHeight"] = preset["height"]

        project.SetRenderSettings(settings)
        job_id = project.AddRenderJob()
        if job_id is None:
            print(f"  [!] Failed to add render job for {platform}")
            continue

        project.StartRendering(job_id)

        # Wait for render to complete
        import time
        while project.IsRenderingInProgress():
            time.sleep(1)

        # Determine output filename
        fmt = preset.get("format", "mp4")
        filename = f"{session_id}_{platform}.{fmt}"
        filepath = output_dir / filename
        resolution = f"{preset.get('width', 0)}x{preset.get('height', 0)}"
        file_size = filepath.stat().st_size if filepath.exists() else 0

        entry = build_deliverable_entry(
            platform=platform,
            filename=filename,
            resolution=resolution,
            duration_sec=duration_sec,
            file_size_bytes=file_size,
            codec=preset.get("codec", ""),
            render_preset=preset_name,
        )
        deliverables.append(entry)
        print(f"  [+] {filename} ({file_size:,} bytes)")

    # Build and save manifest
    manifest = build_manifest(
        session_id=session_id,
        timeline_name=timeline_name,
        duration_sec=duration_sec,
        feeds_used=feeds_used,
        deliverables=deliverables,
    )
    manifest_path = output_dir / "delivery_manifest.json"
    write_sidecar(manifest_path, manifest)
    print(f"\n[OK] Manifest written to {manifest_path}")

    # Write empty analytics scaffold
    analytics = build_analytics(session_id)
    analytics_path = output_dir / "analytics.json"
    write_sidecar(analytics_path, analytics)
    print(f"[OK] Analytics scaffold written to {analytics_path}")

    return manifest


# ---------------------------------------------------------------------------
# Manifest-only (no render)
# ---------------------------------------------------------------------------

def manifest_only(session_id: str) -> dict:
    """Generate a delivery manifest without rendering.

    Reads session metadata from STAGING_DIR if available, otherwise uses
    placeholder values.
    """
    timeline_name = "unknown"
    duration_sec = 0.0
    feeds_used: list[str] = []

    # Try to load session metadata from staging
    session_dir = STAGING_DIR / session_id
    session_manifest_path = session_dir / "_session.json"
    if session_manifest_path.exists():
        session_data = read_session_manifest(session_manifest_path)
        timeline_name = session_data.get("session_id", session_id)
        feeds_used = [
            f.get("feed_id", "") for f in session_data.get("feeds", [])
        ]
        # Sum feed durations for total
        duration_sec = sum(
            f.get("duration", 0.0) for f in session_data.get("feeds", [])
        )

    manifest = build_manifest(
        session_id=session_id,
        timeline_name=timeline_name,
        duration_sec=duration_sec,
        feeds_used=feeds_used,
        deliverables=[],
    )

    # Write manifest to delivery dir
    output_dir = DELIVERY_DIR / session_id
    output_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = output_dir / "delivery_manifest.json"
    write_sidecar(manifest_path, manifest)
    print(f"[OK] Manifest written to {manifest_path}")

    return manifest


# ---------------------------------------------------------------------------
# Status listing
# ---------------------------------------------------------------------------

def show_status() -> None:
    """List deliveries from DELIVERY_DIR."""
    if not DELIVERY_DIR.exists():
        print("[INFO] No delivery directory found.")
        return

    entries = sorted(DELIVERY_DIR.iterdir()) if DELIVERY_DIR.exists() else []
    session_dirs = [e for e in entries if e.is_dir()]

    if not session_dirs:
        print("[INFO] No deliveries found.")
        return

    print(f"\n{'='*60}")
    print(f"  DELIVERIES ({len(session_dirs)} sessions)")
    print(f"{'='*60}")

    for sd in session_dirs:
        manifest_path = sd / "delivery_manifest.json"
        if manifest_path.exists():
            with open(manifest_path, "r", encoding="utf-8") as f:
                m = json.load(f)
            n_deliverables = len(m.get("deliverables", []))
            status = m.get("feedback_loop", {}).get("status", "unknown")
            generated = m.get("generated_at", "?")
            print(f"\n  {sd.name}")
            print(f"    Generated:    {generated}")
            print(f"    Deliverables: {n_deliverables}")
            print(f"    Status:       {status}")
        else:
            print(f"\n  {sd.name}")
            print(f"    (no manifest)")

    print()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    """Entry point: argparse-based CLI for render, manifest, and status."""
    parser = argparse.ArgumentParser(
        description="Resolve render automation and delivery manifest generation."
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--render",
        metavar="SESSION_ID",
        help="Render deliverables for SESSION_ID (requires Resolve running).",
    )
    group.add_argument(
        "--manifest-only",
        metavar="SESSION_ID",
        help="Generate manifest without rendering.",
    )
    group.add_argument(
        "--status",
        action="store_true",
        help="List all deliveries from the delivery directory.",
    )
    group.add_argument(
        "--list",
        action="store_true",
        help="List all sessions from staging.",
    )
    parser.add_argument(
        "--platform",
        action="append",
        choices=list(PLATFORM_MAP.keys()),
        help="Platform(s) to render (default: all). Can be specified multiple times.",
    )

    args = parser.parse_args()

    if args.render:
        render_session(
            session_id=args.render,
            platforms=args.platform,
        )
    elif args.manifest_only:
        manifest_only(args.manifest_only)
    elif args.status:
        show_status()
    elif args.list:
        sessions = list_all_sessions()
        if not sessions:
            print("[INFO] No sessions found in staging.")
        else:
            print(f"\n{'='*60}")
            print(f"  SESSIONS ({len(sessions)})")
            print(f"{'='*60}")
            for s in sessions:
                sid = s.get("session_id", "?")
                n_feeds = len(s.get("feeds", []))
                print(f"  {sid}  ({n_feeds} feeds)")
            print()


if __name__ == "__main__":
    main()
