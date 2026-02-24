"""ArtBot taxonomy labeling — name files per AL naming convention.

Naming: {project}_{subject}_{shot}_{action}_{seq}.{ext}
Per NB11-COMFYUI-AGENT-PROTOCOL.md
"""

import shutil
from pathlib import Path


def build_label(project: str, subject: str, shot: str, action: str, seq: int) -> str:
    """Construct filename (without extension) per taxonomy.

    Format: {project}_{subject}_{shot}_{action}_{seq:03d}
    All parts lowercased.

    Args:
        project: Project prefix, e.g. "al"
        subject: Subject category, e.g. "logo"
        shot: Shot type, e.g. "hero"
        action: Action descriptor, e.g. "idle"
        seq: Sequence number, zero-padded to 3 digits

    Returns:
        Taxonomy filename string without extension.
    """
    parts = [project, subject, shot, action]
    label = "_".join(p.lower() for p in parts)
    return f"{label}_{seq:03d}"


def rename_for_edbot(
    manifest: dict, output_dir: Path, project: str = "al"
) -> list[Path]:
    """Rename and copy selected images to output_dir with taxonomy names.

    Filters manifest images for selected=True only, builds a taxonomy
    label for each, and copies from original path to output_dir with
    the new name preserving the original file extension.

    Args:
        manifest: Dict with "images" list. Each image dict has keys:
            path (str), selected (bool), subject, shot, action, seq (int).
        output_dir: Destination directory. Created if it doesn't exist.
        project: Project prefix for build_label (default "al").

    Returns:
        List of Path objects for the newly created files.
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    results: list[Path] = []

    for image in manifest.get("images", []):
        if not image.get("selected", False):
            continue

        src = Path(image["path"])
        ext = src.suffix  # preserves .png, .mp4, etc.

        label = build_label(
            project=project,
            subject=image["subject"],
            shot=image["shot"],
            action=image["action"],
            seq=image["seq"],
        )

        dest = output_dir / f"{label}{ext}"
        shutil.copy2(src, dest)
        results.append(dest)

    return results
