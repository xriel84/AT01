"""ArtBot tier promotion — move approved assets through quality gates.

Tier directories:
  tier1/     = test images for Tier 1 review
  tier2/     = animated versions for Tier 2 review
  workspace/ = ready for #ai-workspace
  marketing/ = approved for #ai-marketing-interface
"""

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

# Tier number → target directory name
_TIER_MAP: dict[int, str] = {
    1: "tier2",
    2: "workspace",
    3: "marketing",
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def advance(file_path: Path, current_tier: int, base_dir: Path) -> Path:
    """Move a file to the next tier directory.

    Args:
        file_path: Path to the file being promoted.
        current_tier: Current tier number (1, 2, or 3).
        base_dir: Root directory containing all tier subdirectories.

    Returns:
        New Path of the file in the target tier directory.

    Raises:
        ValueError: If current_tier is not 1, 2, or 3.
    """
    if current_tier not in _TIER_MAP:
        raise ValueError(
            f"Invalid tier {current_tier}. Must be one of {sorted(_TIER_MAP)}"
        )

    target_dir = base_dir / _TIER_MAP[current_tier]
    target_dir.mkdir(parents=True, exist_ok=True)

    dest = target_dir / file_path.name
    shutil.move(str(file_path), str(dest))
    return dest


def log_promotion(
    log_path: Path,
    file_name: str,
    from_tier: int,
    to_tier: int,
) -> None:
    """Append a promotion entry to a JSON log file.

    Args:
        log_path: Path to the JSON log file.
        file_name: Name of the promoted file.
        from_tier: Tier the file was promoted from.
        to_tier: Tier the file was promoted to.
    """
    log_path.parent.mkdir(parents=True, exist_ok=True)

    if log_path.exists():
        entries = json.loads(log_path.read_text(encoding="utf-8"))
    else:
        entries = []

    entries.append({
        "file_name": file_name,
        "from_tier": from_tier,
        "to_tier": to_tier,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    })

    log_path.write_text(json.dumps(entries, indent=2), encoding="utf-8")
