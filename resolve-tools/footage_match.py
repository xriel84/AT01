"""footage_match.py -- Group related footage files by naming patterns.

Scans a directory for video files, parses filenames for date/time/camera/
session/take info, and groups files that belong to the same recording session.
Falls back to file creation date proximity when no name pattern matches.
"""

from __future__ import annotations

import argparse
import json
import os
import re
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

VIDEO_EXTS = {".mp4", ".mkv", ".mov", ".avi", ".mxf", ".ts", ".webm"}

# Proximity threshold for fallback grouping: files created within this
# window are considered part of the same session.
PROXIMITY_MINUTES = 5


# ---------------------------------------------------------------------------
# Filename pattern parsers
# ---------------------------------------------------------------------------

def parse_obs_default(filename: str) -> Optional[dict]:
    """Parse OBS default format: '2023-12-08 18-45-03.ext'"""
    m = re.match(r"^(\d{4}-\d{2}-\d{2})\s+(\d{2}-\d{2}-\d{2})", filename)
    if not m:
        return None
    date_str = m.group(1)
    time_str = m.group(2).replace("-", ":")
    dt = datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M:%S")
    # Check for camera suffix like _CAM2
    cam_match = re.search(r"_CAM(\d+)", filename, re.IGNORECASE)
    camera = f"CAM{cam_match.group(1)}" if cam_match else "CAM1"
    return {
        "pattern": "obs_default",
        "datetime": dt,
        "session_key": f"OBS_{date_str}_{time_str.replace(':', '-')}",
        "camera": camera,
    }


def parse_camera_prefix(filename: str) -> Optional[dict]:
    """Parse camera-prefixed: 'CAM1_2023-12-08_session1.ext'"""
    m = re.match(
        r"^(CAM\d+)_(\d{4}-\d{2}-\d{2})_(.+?)(?:\.\w+)?$",
        filename,
        re.IGNORECASE,
    )
    if not m:
        return None
    camera = m.group(1).upper()
    date_str = m.group(2)
    label = m.group(3)
    dt = datetime.strptime(date_str, "%Y-%m-%d")
    return {
        "pattern": "camera_prefix",
        "datetime": dt,
        "session_key": f"{label}_{date_str}",
        "camera": camera,
    }


def parse_take_numbering(filename: str) -> Optional[dict]:
    """Parse take-numbered: 'workshop_take01.ext'"""
    m = re.match(r"^(.+?)_take(\d+)(?:\.\w+)?$", filename, re.IGNORECASE)
    if not m:
        return None
    label = m.group(1)
    take_num = int(m.group(2))
    return {
        "pattern": "take_numbering",
        "datetime": None,
        "session_key": f"{label}_takes",
        "camera": f"take{take_num:02d}",
    }


def parse_custom_label(filename: str) -> Optional[dict]:
    """Parse custom label: 'siggraph_talk_full.ext' (any underscore-separated name)."""
    stem = Path(filename).stem
    # Only match if no other pattern matched and name has at least one underscore
    if "_" in stem and not re.match(r"^\d{4}-\d{2}-\d{2}", stem):
        return {
            "pattern": "custom_label",
            "datetime": None,
            "session_key": stem,
            "camera": "single",
        }
    return None


PARSERS = [parse_obs_default, parse_camera_prefix, parse_take_numbering, parse_custom_label]


def parse_filename(filename: str) -> Optional[dict]:
    """Try each parser in order. Return first match or None."""
    for parser in PARSERS:
        result = parser(filename)
        if result is not None:
            return result
    return None


# ---------------------------------------------------------------------------
# File scanning and grouping
# ---------------------------------------------------------------------------

def get_creation_time(filepath: str) -> datetime:
    """Get file creation time (Windows: birth time, Linux: mtime fallback)."""
    stat = os.stat(filepath)
    # On Windows, st_ctime is creation time
    ctime = getattr(stat, "st_birthtime", stat.st_ctime)
    return datetime.fromtimestamp(ctime)


def scan_directory(scan_dir: str) -> list[dict]:
    """Scan directory for video files. Returns list of file info dicts."""
    root = Path(scan_dir)
    if not root.is_dir():
        print(f"[ERROR] Directory not found: {scan_dir}")
        return []

    files = []
    for entry in sorted(root.iterdir()):
        if entry.is_file() and entry.suffix.lower() in VIDEO_EXTS:
            files.append({
                "path": str(entry),
                "filename": entry.name,
                "creation_time": get_creation_time(str(entry)),
            })
    return files


def group_by_pattern(files: list[dict]) -> tuple[dict[str, list[dict]], list[dict]]:
    """Group files by parsed filename patterns.

    Returns (groups_dict, unmatched_list).
    """
    groups: dict[str, list[dict]] = defaultdict(list)
    unmatched: list[dict] = []

    for finfo in files:
        parsed = parse_filename(finfo["filename"])
        if parsed is not None:
            finfo["parsed"] = parsed
            groups[parsed["session_key"]].append(finfo)
        else:
            unmatched.append(finfo)

    return dict(groups), unmatched


def group_by_proximity(
    files: list[dict],
    threshold_minutes: int = PROXIMITY_MINUTES,
) -> dict[str, list[dict]]:
    """Group unmatched files by creation time proximity.

    Files within threshold_minutes of each other are grouped together.
    """
    if not files:
        return {}

    sorted_files = sorted(files, key=lambda f: f["creation_time"])
    threshold = timedelta(minutes=threshold_minutes)

    groups: dict[str, list[dict]] = {}
    current_group: list[dict] = [sorted_files[0]]
    group_idx = 1

    for finfo in sorted_files[1:]:
        prev_time = current_group[-1]["creation_time"]
        if finfo["creation_time"] - prev_time <= threshold:
            current_group.append(finfo)
        else:
            key = f"proximity_group_{group_idx:03d}"
            groups[key] = current_group
            current_group = [finfo]
            group_idx += 1

    # Flush last group
    key = f"proximity_group_{group_idx:03d}"
    groups[key] = current_group

    return groups


def match_footage(scan_dir: str) -> dict:
    """Main matching function. Returns complete grouping manifest."""
    files = scan_directory(scan_dir)
    if not files:
        return {"scan_dir": scan_dir, "total_files": 0, "groups": {}}

    pattern_groups, unmatched = group_by_pattern(files)
    proximity_groups = group_by_proximity(unmatched)

    # Merge all groups
    all_groups = {}
    for key, group_files in pattern_groups.items():
        all_groups[key] = {
            "match_method": group_files[0].get("parsed", {}).get("pattern", "unknown"),
            "file_count": len(group_files),
            "files": [
                {
                    "filename": f["filename"],
                    "path": f["path"],
                    "camera": f.get("parsed", {}).get("camera", "unknown"),
                }
                for f in group_files
            ],
        }

    for key, group_files in proximity_groups.items():
        all_groups[key] = {
            "match_method": "creation_time_proximity",
            "file_count": len(group_files),
            "files": [
                {
                    "filename": f["filename"],
                    "path": f["path"],
                    "creation_time": f["creation_time"].isoformat(),
                }
                for f in group_files
            ],
        }

    return {
        "scan_dir": scan_dir,
        "total_files": len(files),
        "matched_by_pattern": sum(len(g) for g in pattern_groups.values()),
        "matched_by_proximity": sum(len(g) for g in proximity_groups.values()),
        "group_count": len(all_groups),
        "groups": all_groups,
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="footage_match -- Group related footage files by naming patterns.",
    )
    parser.add_argument(
        "--scan-dir",
        type=str,
        required=True,
        help="Directory to scan for video files",
    )
    parser.add_argument(
        "--output",
        type=str,
        default=None,
        help="Output JSON path (default: footage_groups.json in scan-dir)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print JSON to stdout instead of human-readable output",
    )

    args = parser.parse_args()

    result = match_footage(args.scan_dir)

    # Output
    output_path = args.output or str(Path(args.scan_dir) / "footage_groups.json")

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, default=str)

    if args.json:
        print(json.dumps(result, indent=2, default=str))
    else:
        print(f"\n{'='*60}")
        print(f"  FOOTAGE MATCHING: {args.scan_dir}")
        print(f"{'='*60}")
        print(f"  Total files:          {result['total_files']}")
        print(f"  Matched by pattern:   {result['matched_by_pattern']}")
        print(f"  Matched by proximity: {result['matched_by_proximity']}")
        print(f"  Groups:               {result['group_count']}")
        print()

        for key, group in result["groups"].items():
            method = group["match_method"]
            count = group["file_count"]
            print(f"  [{method}] {key} ({count} file(s))")
            for finfo in group["files"]:
                print(f"    - {finfo['filename']}")
            print()

        print(f"  Manifest written to: {output_path}")
        print(f"{'='*60}\n")


if __name__ == "__main__":
    main()
