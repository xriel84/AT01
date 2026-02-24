"""ArtBot image generation -- ComfyUI API integration.

Builds SDXL workflows, submits them to ComfyUI, and collects output images.
All workflows use 512x512 resolution (VACE constraint -- OOM at 1024).
"""

import json
import time
import urllib.request
import urllib.error
from pathlib import Path

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

COMFYUI_OUTPUT_DIR = Path("C:/NB11/ComfyUI/output")
DEFAULT_SERVER = "http://127.0.0.1:8188"
DEFAULT_CHECKPOINT = "sd_xl_base_1.0.safetensors"
POLL_INTERVAL = 2  # seconds between /history polls


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def build_workflow(prompt: str, settings: dict) -> dict:
    """Build a ComfyUI workflow JSON from prompt and settings.

    Constructs a minimal SDXL workflow payload suitable for POST to
    the ComfyUI /prompt endpoint.  Resolution is forced to 512x512
    regardless of what settings contains (VACE OOM constraint).

    Args:
        prompt: SDXL positive prompt string.
        settings: Dict with cfg_scale, seed, sampler.  May also include
                  negative_prompt, steps, filename_prefix, checkpoint.

    Returns:
        Complete ComfyUI API dict with top-level "prompt" key containing
        the node graph.
    """
    cfg_scale = settings.get("cfg_scale", 7.0)
    seed = settings.get("seed", 42)
    sampler = settings.get("sampler", "euler_ancestral")
    steps = settings.get("steps", 20)
    negative_prompt = settings.get(
        "negative_prompt",
        "photorealistic, 3d render, anime, blurry, watermark, text",
    )
    filename_prefix = settings.get("filename_prefix", "artbot_output")
    checkpoint = settings.get("checkpoint", DEFAULT_CHECKPOINT)

    # Force 512x512 -- never allow override (VACE OOM at 1024)
    width = 512
    height = 512

    workflow = {
        "prompt": {
            # KSampler node
            "3": {
                "class_type": "KSampler",
                "inputs": {
                    "seed": seed,
                    "steps": steps,
                    "cfg": cfg_scale,
                    "sampler_name": sampler,
                    "scheduler": "normal",
                    "denoise": 1.0,
                    "model": ["4", 0],
                    "positive": ["6", 0],
                    "negative": ["7", 0],
                    "latent_image": ["5", 0],
                },
            },
            # CheckpointLoaderSimple
            "4": {
                "class_type": "CheckpointLoaderSimple",
                "inputs": {
                    "ckpt_name": checkpoint,
                },
            },
            # EmptyLatentImage
            "5": {
                "class_type": "EmptyLatentImage",
                "inputs": {
                    "width": width,
                    "height": height,
                    "batch_size": 1,
                },
            },
            # CLIPTextEncode (positive)
            "6": {
                "class_type": "CLIPTextEncode",
                "inputs": {
                    "text": prompt,
                    "clip": ["4", 1],
                },
            },
            # CLIPTextEncode (negative)
            "7": {
                "class_type": "CLIPTextEncode",
                "inputs": {
                    "text": negative_prompt,
                    "clip": ["4", 1],
                },
            },
            # VAEDecode
            "8": {
                "class_type": "VAEDecode",
                "inputs": {
                    "samples": ["3", 0],
                    "vae": ["4", 2],
                },
            },
            # SaveImage
            "9": {
                "class_type": "SaveImage",
                "inputs": {
                    "filename_prefix": filename_prefix,
                    "images": ["8", 0],
                },
            },
        }
    }

    return workflow


def submit_batch(
    workflows: list[dict],
    server: str = DEFAULT_SERVER,
) -> list[dict]:
    """Submit a batch of workflows to ComfyUI API.

    POSTs each workflow to {server}/prompt and collects the returned
    prompt_id values.

    Args:
        workflows: List of workflow dicts from build_workflow().
        server: ComfyUI server URL (default http://127.0.0.1:8188).

    Returns:
        List of dicts.  On success each has {"prompt_id": str, "status": "submitted"}.
        On connection failure returns [{"status": "error", "error": str}].
    """
    results: list[dict] = []
    url = f"{server}/prompt"

    for workflow in workflows:
        try:
            data = json.dumps(workflow).encode("utf-8")
            req = urllib.request.Request(
                url,
                data=data,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req) as resp:
                body = json.loads(resp.read())
                prompt_id = body.get("prompt_id", "unknown")
                results.append({
                    "prompt_id": prompt_id,
                    "status": "submitted",
                })
        except (ConnectionRefusedError, urllib.error.URLError) as exc:
            results.append({
                "status": "error",
                "error": str(exc),
            })
        except Exception as exc:  # noqa: BLE001
            results.append({
                "status": "error",
                "error": str(exc),
            })

    return results


def collect_results(
    prompt_ids: list[str],
    server: str = DEFAULT_SERVER,
    timeout: int = 300,
) -> list[Path]:
    """Poll ComfyUI for completed outputs.

    Repeatedly queries {server}/history/{prompt_id} until each job shows
    a completed status or the timeout is exceeded.

    Args:
        prompt_ids: List of prompt IDs from submit_batch().
        server: ComfyUI server URL.
        timeout: Max seconds to wait for all results.

    Returns:
        List of Path objects pointing to generated image files.
        Returns whatever has been collected when timeout expires.
    """
    collected: list[Path] = []
    remaining = set(prompt_ids)
    deadline = time.time() + timeout

    while remaining and time.time() < deadline:
        for pid in list(remaining):
            try:
                url = f"{server}/history/{pid}"
                req = urllib.request.Request(url)
                with urllib.request.urlopen(req) as resp:
                    history = json.loads(resp.read())

                if pid not in history:
                    continue

                entry = history[pid]
                status = entry.get("status", {})
                if not status.get("completed", False):
                    continue

                # Extract output images from all output nodes
                outputs = entry.get("outputs", {})
                for _node_id, node_out in outputs.items():
                    images = node_out.get("images", [])
                    for img in images:
                        filename = img.get("filename", "")
                        subfolder = img.get("subfolder", "")
                        if filename:
                            if subfolder:
                                path = COMFYUI_OUTPUT_DIR / subfolder / filename
                            else:
                                path = COMFYUI_OUTPUT_DIR / filename
                            collected.append(path)

                remaining.discard(pid)

            except (ConnectionRefusedError, urllib.error.URLError):
                # Server unreachable -- will retry on next loop
                pass
            except Exception:  # noqa: BLE001
                # Unexpected error -- skip this ID for now
                pass

        if remaining and time.time() < deadline:
            time.sleep(POLL_INTERVAL)

    return collected
