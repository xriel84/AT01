"""ArtBot animation -- still image to animation via ComfyUI VACE/AnimateDiff.

All animations use 512x512 resolution (VACE OOM constraint).
Reuses generate.submit_batch and generate.collect_results for ComfyUI communication.
"""

import json
from pathlib import Path

from generate import submit_batch


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_SETTINGS = {
    "cfg_scale": 7.0,
    "steps": 20,
    "frames": 16,
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def build_animate_workflow(
    image_path: Path,
    settings: dict | None = None,
) -> dict:
    """Build a ComfyUI VACE/AnimateDiff workflow for animating a still image.

    Always forces 512x512 resolution (VACE OOM constraint at 1024).
    The source image path is included in the workflow via a LoadImage node.

    Args:
        image_path: Path to the source still image.
        settings: Optional dict with cfg_scale, steps, frames overrides.
                  Defaults to cfg_scale=7.0, steps=20, frames=16.

    Returns:
        Complete ComfyUI API dict with top-level "prompt" key containing
        the VACE/AnimateDiff node graph.
    """
    s = {**DEFAULT_SETTINGS, **(settings or {})}
    cfg_scale = s.get("cfg_scale", DEFAULT_SETTINGS["cfg_scale"])
    steps = s.get("steps", DEFAULT_SETTINGS["steps"])
    frames = s.get("frames", DEFAULT_SETTINGS["frames"])
    seed = s.get("seed", 42)
    sampler = s.get("sampler", "euler_ancestral")
    filename_prefix = s.get("filename_prefix", "artbot_anim")

    # Force 512x512 -- never allow override (VACE OOM at 1024)
    width = 512
    height = 512

    workflow = {
        "prompt": {
            # LoadImage -- source still frame
            "1": {
                "class_type": "LoadImage",
                "inputs": {
                    "image": str(image_path),
                },
            },
            # ImageScale -- force 512x512
            "2": {
                "class_type": "ImageScale",
                "inputs": {
                    "image": ["1", 0],
                    "width": width,
                    "height": height,
                    "upscale_method": "bilinear",
                    "crop": "center",
                },
            },
            # CheckpointLoaderSimple
            "3": {
                "class_type": "CheckpointLoaderSimple",
                "inputs": {
                    "ckpt_name": "sd_xl_base_1.0.safetensors",
                },
            },
            # AnimateDiffLoader
            "4": {
                "class_type": "AnimateDiffLoader",
                "inputs": {
                    "model": ["3", 0],
                    "model_name": "v3_sd15_adapter.ckpt",
                    "beta_schedule": "linear",
                },
            },
            # VAEEncode -- encode source image to latent
            "5": {
                "class_type": "VAEEncode",
                "inputs": {
                    "pixels": ["2", 0],
                    "vae": ["3", 2],
                },
            },
            # RepeatLatentBatch -- expand single frame to N frames
            "6": {
                "class_type": "RepeatLatentBatch",
                "inputs": {
                    "samples": ["5", 0],
                    "amount": frames,
                },
            },
            # CLIPTextEncode (positive) -- animate motion
            "7": {
                "class_type": "CLIPTextEncode",
                "inputs": {
                    "text": "subtle animation, gentle motion, looping",
                    "clip": ["3", 1],
                },
            },
            # CLIPTextEncode (negative)
            "8": {
                "class_type": "CLIPTextEncode",
                "inputs": {
                    "text": "static, still, frozen, blurry, distorted",
                    "clip": ["3", 1],
                },
            },
            # KSampler -- denoise from latent image
            "9": {
                "class_type": "KSampler",
                "inputs": {
                    "seed": seed,
                    "steps": steps,
                    "cfg": cfg_scale,
                    "sampler_name": sampler,
                    "scheduler": "normal",
                    "denoise": 0.5,
                    "model": ["4", 0],
                    "positive": ["7", 0],
                    "negative": ["8", 0],
                    "latent_image": ["6", 0],
                },
            },
            # VAEDecode
            "10": {
                "class_type": "VAEDecode",
                "inputs": {
                    "samples": ["9", 0],
                    "vae": ["3", 2],
                },
            },
            # SaveImage
            "11": {
                "class_type": "SaveImage",
                "inputs": {
                    "filename_prefix": filename_prefix,
                    "images": ["10", 0],
                },
            },
        }
    }

    return workflow


def animate_batch(
    manifest: dict,
    server: str = "http://127.0.0.1:8188",
) -> list[dict]:
    """Filter manifest for animate=True images, build workflows, and submit.

    Reads manifest["images"] entries.  Each entry must have:
      - "path": str -- file path to the source image
      - "animate": bool -- whether to animate this image

    Only images with animate=True are submitted.

    Args:
        manifest: Dict with "images" list of image entry dicts.
        server: ComfyUI server URL (default http://127.0.0.1:8188).

    Returns:
        List of result dicts.  Each has at minimum a "status" key.
        On success: {"image": str, "status": "submitted", "prompt_id": str}.
        On error: {"image": str, "status": "error", "error": str}.
    """
    images = manifest.get("images", [])
    to_animate = [img for img in images if img.get("animate", False)]

    if not to_animate:
        return []

    # Build a workflow for each image
    workflows = []
    for img_entry in to_animate:
        image_path = Path(img_entry["path"])
        wf = build_animate_workflow(image_path)
        workflows.append(wf)

    # Submit all workflows via generate.submit_batch
    submit_results = submit_batch(workflows, server=server)

    # Merge submission results with image paths
    results = []
    for img_entry, sub_result in zip(to_animate, submit_results):
        entry = {
            "image": img_entry["path"],
            **sub_result,
        }
        results.append(entry)

    return results
