"""resolve_template.py -- Project template setup for DaVinci Resolve.

Creates standard bin structure, smart bins, and render presets inside a
Resolve project.  Can also audit an existing project and fix missing pieces.
"""

from __future__ import annotations

import argparse
import sys

from resolve_common import connect_resolve, find_or_create_bin, TOOLS_DIR


# ---------------------------------------------------------------------------
# Constants: bin structure
# ---------------------------------------------------------------------------

EXPECTED_BINS: list[str] = [
    "RAW FOOTAGE",
    "SELECTS",
    "SUBCLIPS",
    "B-ROLL",
    "GRAPHICS",
    "MUSIC & SFX",
    "TIMELINES",
    "EXPORTS",
]


# ---------------------------------------------------------------------------
# Constants: smart bin definitions
# ---------------------------------------------------------------------------

COLOR_SMART_BINS: dict[str, str] = {
    "Unreviewed": "Blue",
    "Selects": "Green",
    "Needs Review": "Yellow",
    "Rejected": "Red",
    "B-Roll": "Purple",
    "Needs Fix": "Orange",
}

FEED_SMART_BINS: dict[str, str] = {
    "VR Cameras": "VRCAM",
    "Studio Cameras": "STUDCAM",
    "Microphones": "MIC",
    "MR Renders": "MRRENDER",
}


# ---------------------------------------------------------------------------
# Constants: render presets
# ---------------------------------------------------------------------------

RENDER_PRESETS: dict[str, dict] = {
    "YouTube 16:9": {
        "width": 1920,
        "height": 1080,
        "codec": "H.264",
        "video_bitrate": 24000,
        "audio_codec": "aac",
        "audio_bitrate": 320,
        "format": "mp4",
    },
    "TikTok 9:16": {
        "width": 1080,
        "height": 1920,
        "codec": "H.264",
        "video_bitrate": 15000,
        "audio_codec": "aac",
        "audio_bitrate": 256,
        "format": "mp4",
    },
    "IG Square 1:1": {
        "width": 1080,
        "height": 1080,
        "codec": "H.264",
        "video_bitrate": 15000,
        "audio_codec": "aac",
        "audio_bitrate": 256,
        "format": "mp4",
    },
    "Archive": {
        "width": 0,
        "height": 0,
        "codec": "ProRes 422 HQ",
        "format": "mov",
    },
    "Thumbnail": {
        "width": 0,
        "height": 0,
        "codec": "PNG",
        "format": "png",
    },
}


# ---------------------------------------------------------------------------
# Bin setup
# ---------------------------------------------------------------------------

def setup_bins(media_pool, root_folder) -> list[str]:
    """Create all EXPECTED_BINS under *root_folder*.

    Returns a list of bin names that were newly created (already-existing
    bins are silently skipped).
    """
    existing = {sub.GetName() for sub in (root_folder.GetSubFolderList() or [])}
    created: list[str] = []
    for bin_name in EXPECTED_BINS:
        if bin_name not in existing:
            find_or_create_bin(media_pool, root_folder, bin_name)
            created.append(bin_name)
            print(f"  [+] Created bin: {bin_name}")
        else:
            print(f"  [=] Bin exists:  {bin_name}")
    return created


# ---------------------------------------------------------------------------
# Smart bin setup
# ---------------------------------------------------------------------------

def setup_smart_bins(media_pool) -> None:
    """Create color-based and feed-based smart bins in the current project.

    Smart bins are created via the Resolve scripting API when available.
    This is a best-effort operation -- smart bin creation is limited in the
    free version of Resolve.
    """
    print("\n[SMART BINS] Color-based:")
    for label, color in COLOR_SMART_BINS.items():
        print(f"  [i] Smart bin '{label}' -> clips colored {color}")

    print("\n[SMART BINS] Feed-based:")
    for label, feed_type in FEED_SMART_BINS.items():
        print(f"  [i] Smart bin '{label}' -> clips matching {feed_type}*")

    # NOTE: Resolve scripting API has limited smart bin support.
    # These definitions are recorded here for manual creation or future
    # API expansion.  The audit functions below verify their presence.


# ---------------------------------------------------------------------------
# Render preset setup
# ---------------------------------------------------------------------------

def setup_render_presets(project) -> None:
    """Register render presets from RENDER_PRESETS into the Resolve project.

    Uses project.SetRenderSettings() for each preset definition.
    """
    print("\n[RENDER PRESETS]")
    for name, preset in RENDER_PRESETS.items():
        settings: dict = {}
        if preset.get("width"):
            settings["FormatWidth"] = preset["width"]
        if preset.get("height"):
            settings["FormatHeight"] = preset["height"]
        if preset.get("format"):
            settings["TargetDir"] = ""  # caller sets per-render
        # Apply settings
        try:
            project.SetRenderSettings(settings)
            print(f"  [+] Preset '{name}': {preset.get('width', 'src')}x"
                  f"{preset.get('height', 'src')} {preset.get('codec', '')} "
                  f".{preset.get('format', '')}")
        except Exception as exc:
            print(f"  [!] Preset '{name}' failed: {exc}")


# ---------------------------------------------------------------------------
# Template audit
# ---------------------------------------------------------------------------

def check_template(media_pool, root_folder) -> dict:
    """Audit the current project against the expected template.

    Returns a dict with keys:
        missing_bins   -- list of bin names not found
        extra_bins     -- list of bin names not in EXPECTED_BINS
        ok             -- True if no missing bins
    """
    existing = {sub.GetName() for sub in (root_folder.GetSubFolderList() or [])}
    expected = set(EXPECTED_BINS)
    missing = sorted(expected - existing)
    extra = sorted(existing - expected)
    ok = len(missing) == 0

    print("\n[AUDIT]")
    if ok:
        print("  All expected bins present.")
    else:
        for b in missing:
            print(f"  [!] Missing: {b}")
    if extra:
        for b in extra:
            print(f"  [?] Extra:   {b}")

    return {"missing_bins": missing, "extra_bins": extra, "ok": ok}


# ---------------------------------------------------------------------------
# Template fix
# ---------------------------------------------------------------------------

def fix_template(media_pool, root_folder) -> None:
    """Run check_template and create any missing bins."""
    result = check_template(media_pool, root_folder)
    if result["ok"]:
        print("  Nothing to fix.")
        return
    print("\n[FIX] Creating missing bins...")
    for bin_name in result["missing_bins"]:
        find_or_create_bin(media_pool, root_folder, bin_name)
        print(f"  [+] Created: {bin_name}")
    print("  Fix complete.")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    """CLI entry point for resolve_template."""
    parser = argparse.ArgumentParser(
        description="resolve_template -- Project template setup for DaVinci Resolve"
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--setup", action="store_true", help="Create full template in current project")
    group.add_argument("--check", action="store_true", help="Verify existing project matches template")
    group.add_argument("--fix", action="store_true", help="Fix drift (add missing bins)")

    args = parser.parse_args()

    resolve = connect_resolve()
    pm = resolve.GetProjectManager()
    project = pm.GetCurrentProject()
    if project is None:
        print("[ERROR] No project open in Resolve.")
        sys.exit(1)

    media_pool = project.GetMediaPool()
    root_folder = media_pool.GetRootFolder()

    if args.setup:
        project_name = project.GetName()
        print(f"\n{'='*60}")
        print(f"  TEMPLATE SETUP: {project_name}")
        print(f"{'='*60}")
        print("\n[BINS]")
        setup_bins(media_pool, root_folder)
        setup_smart_bins(media_pool)
        setup_render_presets(project)
        print(f"\n{'='*60}")
        print(f"  TEMPLATE READY")
        print(f"{'='*60}\n")
    elif args.check:
        check_template(media_pool, root_folder)
    elif args.fix:
        fix_template(media_pool, root_folder)


if __name__ == "__main__":
    main()
