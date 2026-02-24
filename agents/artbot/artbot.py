"""ArtBot — Image generation, selection, animation, and promotion pipeline.

Usage:
    py -3.12 artbot.py brief --text "animated logo for intro"
    py -3.12 artbot.py generate --brief brief.json --variations 4
    py -3.12 artbot.py review --images-dir ./tier1 --brief brief.json
    py -3.12 artbot.py animate --manifest review.json
    py -3.12 artbot.py label --manifest review.json --output-dir ./labeled
    py -3.12 artbot.py promote --file logo_001.png --tier 1 --base-dir ./artbot-output
"""

import argparse
import json
import sys
from pathlib import Path


# ---------------------------------------------------------------------------
# Subcommand handlers
# ---------------------------------------------------------------------------

def cmd_brief(args: argparse.Namespace) -> None:
    """Parse human text into an SDXL-ready brief."""
    from brief import parse_brief, build_prompt, load_library

    parsed = parse_brief(args.text)
    library = load_library()
    prompt = build_prompt(parsed, library)

    result = {**parsed, **prompt}
    print(json.dumps(result, indent=2))


def cmd_generate(args: argparse.Namespace) -> None:
    """Load a brief JSON and submit generation variations to ComfyUI."""
    from brief import generate_variations
    from generate import build_workflow, submit_batch

    brief_data = json.loads(Path(args.brief).read_text(encoding="utf-8"))
    positive = brief_data.get("positive", brief_data.get("raw_text", ""))
    negative = brief_data.get("negative", "")

    variations = generate_variations(positive, n=args.variations)

    workflows = []
    for var in variations:
        settings = {
            "cfg_scale": var["cfg_scale"],
            "seed": var["seed"],
            "sampler": var["sampler"],
            "negative_prompt": negative,
        }
        wf = build_workflow(var["prompt"], settings)
        workflows.append(wf)

    results = submit_batch(workflows)
    print(json.dumps(results, indent=2))


def cmd_review(args: argparse.Namespace) -> None:
    """Build a review manifest from generated images."""
    from review import build_review_manifest, save_manifest

    images_dir = Path(args.images_dir)
    images = sorted(
        p for p in images_dir.iterdir()
        if p.is_file() and p.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"}
    )

    brief_data = json.loads(Path(args.brief).read_text(encoding="utf-8"))

    manifest = build_review_manifest(images, brief_data, tier=args.tier)

    out_path = images_dir / "review_manifest.json"
    save_manifest(manifest, out_path)
    print(json.dumps({"manifest": str(out_path), "images": len(images)}, indent=2))


def cmd_animate(args: argparse.Namespace) -> None:
    """Submit selected images for animation via ComfyUI."""
    from animate import animate_batch

    manifest = json.loads(Path(args.manifest).read_text(encoding="utf-8"))
    results = animate_batch(manifest, server=args.server)
    print(json.dumps(results, indent=2))


def cmd_label(args: argparse.Namespace) -> None:
    """Rename selected images per AL taxonomy convention."""
    from label import rename_for_edbot

    manifest = json.loads(Path(args.manifest).read_text(encoding="utf-8"))
    output_dir = Path(args.output_dir)

    labeled = rename_for_edbot(manifest, output_dir, project=args.project)
    print(json.dumps([str(p) for p in labeled], indent=2))


def cmd_promote(args: argparse.Namespace) -> None:
    """Advance a file to the next quality tier."""
    from promote import advance, log_promotion

    file_path = Path(args.file)
    base_dir = Path(args.base_dir)
    current_tier = args.tier

    new_path = advance(file_path, current_tier, base_dir)

    log_path = base_dir / "promotion_log.json"
    # _TIER_MAP: 1->tier2, 2->workspace, 3->marketing
    to_tier = current_tier + 1
    log_promotion(log_path, file_path.name, from_tier=current_tier, to_tier=to_tier)

    print(json.dumps({
        "file": str(new_path),
        "from_tier": current_tier,
        "to_tier": to_tier,
    }, indent=2))


# ---------------------------------------------------------------------------
# CLI parser
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    """Build the argparse parser with all subcommands."""
    parser = argparse.ArgumentParser(
        prog="artbot",
        description="ArtBot — Image generation, selection, animation, and promotion pipeline.",
    )
    parser.add_argument(
        "--json", action="store_true",
        help="Force JSON output (default for most subcommands)",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # brief ---
    p_brief = sub.add_parser("brief", help="Parse human text into SDXL brief")
    p_brief.add_argument("--text", required=True, help="Human description of desired image")

    # generate ---
    p_gen = sub.add_parser("generate", help="Generate image variations via ComfyUI")
    p_gen.add_argument("--brief", required=True, help="Path to brief JSON file")
    p_gen.add_argument("--variations", type=int, default=4, help="Number of variations (default 4)")

    # review ---
    p_rev = sub.add_parser("review", help="Build review manifest from generated images")
    p_rev.add_argument("--images-dir", required=True, help="Directory of generated images")
    p_rev.add_argument("--brief", required=True, help="Path to brief JSON file")
    p_rev.add_argument("--tier", type=int, default=1, help="Asset tier level (default 1)")

    # animate ---
    p_anim = sub.add_parser("animate", help="Animate selected images via ComfyUI")
    p_anim.add_argument("--manifest", required=True, help="Path to review manifest JSON")
    p_anim.add_argument("--server", default="http://127.0.0.1:8188", help="ComfyUI server URL")

    # label ---
    p_label = sub.add_parser("label", help="Rename files per AL taxonomy convention")
    p_label.add_argument("--manifest", required=True, help="Path to review manifest JSON")
    p_label.add_argument("--output-dir", required=True, help="Destination directory for labeled files")
    p_label.add_argument("--project", default="al", help="Project prefix (default 'al')")

    # promote ---
    p_promote = sub.add_parser("promote", help="Advance file to next quality tier")
    p_promote.add_argument("--file", required=True, help="Path to file being promoted")
    p_promote.add_argument("--tier", type=int, required=True, help="Current tier number (1, 2, or 3)")
    p_promote.add_argument("--base-dir", required=True, help="Root directory with tier subdirectories")

    return parser


def main() -> None:
    """Entry point."""
    parser = build_parser()
    args = parser.parse_args()

    dispatch = {
        "brief": cmd_brief,
        "generate": cmd_generate,
        "review": cmd_review,
        "animate": cmd_animate,
        "label": cmd_label,
        "promote": cmd_promote,
    }

    handler = dispatch.get(args.command)
    if handler is None:
        parser.print_help()
        sys.exit(1)

    handler(args)


if __name__ == "__main__":
    main()
