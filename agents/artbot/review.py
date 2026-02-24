"""ArtBot review manifest — JSON output for review UI consumption.

Builds structured manifests from generated images so any review UI
(including JP's iterations) can display them for Tier 1/2 selection.
"""

import json
from pathlib import Path


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def build_review_manifest(
    images: list[Path],
    brief: dict,
    tier: int = 1,
) -> dict:
    """Create a JSON-serializable manifest from generated images.

    Args:
        images: List of Path objects pointing to generated image files.
        brief: Original brief dict (from parse_brief or equivalent).
        tier: Asset tier level (default 1).  Tier 1 = static, Tier 2 = animated.

    Returns:
        Dict with keys: brief, tier, images.  Each image entry has
        path (str), index (int), tier (int), selected (bool), animate (bool).
    """
    entries = []
    for i, img_path in enumerate(images):
        entries.append({
            "path": str(img_path),
            "index": i,
            "tier": tier,
            "selected": False,
            "animate": False,
        })

    return {
        "brief": brief,
        "tier": tier,
        "images": entries,
    }


def mark_selection(
    manifest: dict,
    selected: list[int],
    animate: list[int] | None = None,
) -> dict:
    """Mark which images are selected and which need animation.

    Args:
        manifest: Manifest dict from build_review_manifest().
        selected: List of image indices to mark as selected.
        animate: List of image indices to mark for animation.
                 Only applied to images that are also selected.

    Returns:
        Updated manifest dict with selection and animation flags set.
    """
    if animate is None:
        animate = []

    selected_set = set(selected)
    animate_set = set(animate)

    for entry in manifest["images"]:
        idx = entry["index"]
        is_selected = idx in selected_set
        entry["selected"] = is_selected
        # Only mark animate if the image is also selected
        entry["animate"] = is_selected and idx in animate_set

    return manifest


def save_manifest(manifest: dict, output: Path) -> Path:
    """Write manifest to disk as JSON.

    Args:
        manifest: Manifest dict to serialize.
        output: Destination file path.

    Returns:
        Path object pointing to the written file.
    """
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return output
