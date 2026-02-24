"""ArtBot brief parser -- convert human NLP to SDXL-optimized prompts.

Parses natural language briefs, converts to SDXL prompt language using
a keyword library, and generates N variations with parameter sweeps.
"""

import json
import random
from pathlib import Path

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

ASSET_TYPES = (
    "logo", "frame", "banner", "icon", "thumbnail",
    "badge", "overlay", "splash", "avatar", "sprite",
)

ANIMATION_KEYWORDS = ("animated", "animation", "motion", "animate", "moving")

STYLE_KEYWORDS = (
    "noir", "gold", "dark", "bright", "minimal", "clean",
    "retro", "vintage", "neon", "bold", "flat", "geometric",
    "warm", "cool", "pastel", "metallic", "glossy", "matte",
)

DEFAULT_QUALITY_TAGS = "masterpiece, best quality, highly detailed"
DEFAULT_NEGATIVE = (
    "photorealistic, 3d render, anime, modern, gradient shading, "
    "soft edges, blurry, watermark, text, signature, photograph"
)

SAMPLERS = ("euler_ancestral", "dpmpp_2m", "dpmpp_sde", "euler")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def parse_brief(text: str) -> dict:
    """Parse a human brief into structured fields.

    Args:
        text: Natural language description, e.g. "animated logo spinning gold"

    Returns:
        dict with keys: asset_type, animated, style_hints, raw_text
    """
    lower = text.lower()

    # Detect animation intent
    animated = any(kw in lower for kw in ANIMATION_KEYWORDS)

    # Detect asset type (first match wins)
    asset_type = "generic"
    for at in ASSET_TYPES:
        if at in lower:
            asset_type = at
            break

    # Extract style hints
    style_hints = [s for s in STYLE_KEYWORDS if s in lower]

    return {
        "asset_type": asset_type,
        "animated": animated,
        "style_hints": style_hints,
        "raw_text": text,
    }


def build_prompt(brief: dict, library: dict | None = None) -> dict:
    """Convert a parsed brief into SDXL prompt strings.

    Combines brief keywords with library quality_tags and style_presets.

    Args:
        brief: Output of parse_brief()
        library: sdxl_library.json contents (NLP->SDXL term mapping), or None

    Returns:
        dict with keys: positive (str), negative (str)
    """
    parts: list[str] = []

    # Start with asset type
    asset_type = brief.get("asset_type", "generic")
    if asset_type != "generic":
        parts.append(asset_type)

    # Add raw text context (cleaned)
    raw = brief.get("raw_text", "")
    if raw:
        parts.append(raw)

    # Library-driven style expansion
    if library:
        style_map = library.get("style", {})
        for hint in brief.get("style_hints", []):
            if hint in style_map:
                parts.append(style_map[hint])

        # Quality tags from library
        quality_map = library.get("quality", {})
        if quality_map:
            # Use first available quality preset
            first_quality = next(iter(quality_map.values()))
            parts.append(first_quality)
        else:
            parts.append(DEFAULT_QUALITY_TAGS)
    else:
        parts.append(DEFAULT_QUALITY_TAGS)

    positive = ", ".join(p.strip() for p in parts if p.strip())

    # Negative prompt
    if library and "negative" in library:
        neg_map = library["negative"]
        negative = neg_map.get("default", DEFAULT_NEGATIVE)
    else:
        negative = DEFAULT_NEGATIVE

    return {
        "positive": positive,
        "negative": negative,
    }


def generate_variations(base_prompt: str, n: int = 4) -> list[dict]:
    """Generate N prompt variations with parameter sweeps.

    Each variation gets a unique seed, slightly different cfg_scale,
    and a sampler from a small rotating set.

    Args:
        base_prompt: SDXL positive prompt string
        n: Number of variations to generate (default 4)

    Returns:
        List of dicts, each with keys: prompt, cfg_scale, seed, sampler
    """
    variations = []
    base_cfg = 7.0
    step_size = 0.5

    for i in range(n):
        # Spread cfg_scale around 7.0: 6.0, 6.5, 7.0, 7.5, 8.0, ...
        offset = (i - n // 2) * step_size
        cfg = round(base_cfg + offset, 1)

        seed = random.randint(1, 2**31 - 1)
        sampler = SAMPLERS[i % len(SAMPLERS)]

        variations.append({
            "prompt": base_prompt,
            "cfg_scale": cfg,
            "seed": seed,
            "sampler": sampler,
        })

    return variations


def load_library(path: Path | None = None) -> dict:
    """Load the SDXL keyword library from JSON.

    Args:
        path: Path to sdxl_library.json. Defaults to prompts/sdxl_library.json
              relative to this file.

    Returns:
        dict with library contents, or empty dict if file missing.
    """
    if path is None:
        path = Path(__file__).resolve().parent / "prompts" / "sdxl_library.json"

    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {}
