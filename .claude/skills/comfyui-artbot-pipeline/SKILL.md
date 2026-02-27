---
name: comfyui-artbot-pipeline
description: Submit ComfyUI workflows, verify outputs, enforce naming conventions, and manage the ArtBot asset pipeline for AT01/JP01. Use this skill whenever the user mentions ComfyUI, image generation, VACE animation, transparent PNGs, asset pipeline, ArtBot, sprite generation, LayerDiffusion, thumbnail generation, or any workflow submission to localhost:8188. Also trigger on "generate image", "run workflow", "check output", "promote asset", or asset naming questions.
---

# ComfyUI ArtBot Pipeline

## Environment
- ComfyUI: `C:\ComfyUI_windows_portable\ComfyUI\` | v0.12.3 | http://127.0.0.1:8188
- GPU: RTX A6000 48GB VRAM
- Output root: `C:\ComfyUI_windows_portable\ComfyUI\output\`

## Output Folder Convention

```
output/at/    ← AT01 assets (Art Deco style)
  at_{subject}_{shot}_{action}_{seq}.{ext}

output/jp/    ← JP01 assets (Steampunk style)
  jp_{subject}_{shot}_{action}_{seq}.{ext}

output/video/ ← Rendered video (both prefixes allowed)
  {prefix}_{subject}_render_{seq}.mp4
```

### Naming Convention
```
{prefix}_{subject}_{shot}_{action}_{seq}.{ext}

prefix:   at | jp (NEVER cross)
subject:  gear, bolt, cog, agent, desk, etc.
shot:     mc (medium center), wl (wide left), etc. — 3×3 grid (W/M/C × L/C/R)
action:   still, idle, loop, work, review, open, interact, disassemble, fun-*
seq:      001, 002, ...
ext:      png (stills), apng/webp (animated), mp4 (video)
```

### Shot Grid
| | Left (L) | Center (C) | Right (R) |
|---|---|---|---|
| Wide (W) | wl | wc | wr |
| Medium (M) | ml | mc | mr |
| Close (C) | cl | cc | cr |

Plus depth layers: f (foreground), m (midground), b (background)

## HARD LIMITS

- **512×512 VACE maximum** — OOM at 1024. Non-negotiable.
- **1024×1024 for SDXL stills** — LayerDiffusion transparent PNGs
- **VACE 14B fp16** — loaded model, ~14GB VRAM
- No creative decisions — human gate on all generated images

## Workflow Submission (Python)

```python
import json, urllib.request

def submit_workflow(workflow_json, server="http://127.0.0.1:8188"):
    data = json.dumps({"prompt": workflow_json}).encode()
    req = urllib.request.Request(f"{server}/prompt", data=data,
          headers={"Content-Type": "application/json"})
    resp = urllib.request.urlopen(req)
    return json.loads(resp.read())["prompt_id"]

def poll_status(prompt_id, server="http://127.0.0.1:8188"):
    resp = urllib.request.urlopen(f"{server}/history/{prompt_id}")
    history = json.loads(resp.read())
    return history.get(prompt_id, {})
```

### PowerShell Submission
```powershell
$body = @{ prompt = (Get-Content workflow.json | ConvertFrom-Json) } | ConvertTo-Json -Depth 20
$resp = Invoke-RestMethod -Uri "http://127.0.0.1:8188/prompt" -Method POST -Body $body -ContentType "application/json"
$promptId = $resp.prompt_id
# Poll: Invoke-RestMethod "http://127.0.0.1:8188/history/$promptId"
```

## Transparency Verification

After every generation, verify alpha channel:

```powershell
py -3.12 -c "
from PIL import Image
import numpy as np, sys
img = Image.open(sys.argv[1])
print(f'Format: {img.format} | Mode: {img.mode} | Size: {img.size}')
if hasattr(img, 'n_frames'): print(f'Frames: {img.n_frames}')
if 'A' in (img.mode or ''):
    a = np.array(img.split()[-1])
    tp = (a < 128).sum() / a.size * 100
    print(f'Alpha range: {a.min()}-{a.max()} | Transparent pixels: {tp:.1f}%')
    print('TRANSPARENCY: CONFIRMED' if tp > 5 else 'TRANSPARENCY: SUSPECT')
else:
    print('TRANSPARENCY: NONE — no alpha channel')
" "PATH_TO_FILE"
```

## Generation Parameters

### SDXL Stills (LayerDiffusion)
- Resolution: 1024×1024
- CFG: 5
- Steps: 30
- Sampler: DPM++ 2M SDE Karras
- Background: Transparent (LayerDiffusion Conv Injection)
- Time: ~15-45 sec
- Checkpoint: JuggernautXL (primary) or DreamShaper

### VACE Animation
- Resolution: 512×512 ONLY
- Input: transparent PNG still
- Output: APNG or WebP with alpha
- Workflow: Animate_PNG_Artbot.json (JP's verified workflow)
- Time: ~3-5 min
- Model: VACE 14B fp16

## Promote Flow

```
ComfyUI output/ → draft/ → [HUMAN GATE] → approved/ → deployed/
```

### Asset Manifest
After promoting to approved/:
```python
import json, datetime
from pathlib import Path

def write_manifest(approved_dir, prefix="jp"):
    assets = []
    for f in sorted(Path(approved_dir).glob(f'{prefix}_*')):
        assets.append({
            'filename': f.name,
            'size_bytes': f.stat().st_size,
            'status': 'approved',
            'transparent': True,
            'source': 'layerdiffusion' if 'still' in f.name else 'animate-png-artbot',
            'created': datetime.datetime.now().isoformat()
        })
    manifest = {'updated': datetime.datetime.now().isoformat(), 'assets': assets}
    Path(approved_dir).parent.joinpath(f'{prefix}_asset_manifest.json').write_text(
        json.dumps(manifest, indent=2))
```

## Style Firewall

| Prefix | Style | Time | Mood | Checkpoint |
|--------|-------|------|------|------------|
| at_ | Constructivist Art Deco | Night | Dark, dramatic | JuggernautXL |
| jp_ | Steampunk | Day | Cheerful, warm | JuggernautXL |

Save node prefix in workflow JSON must match: `at/at_` or `jp/jp_`

## LOD Tiers
- LOD-0: Hero assets, highest quality
- LOD-1: Primary UI elements
- LOD-2: Supporting visuals
- LOD-3: Background/ambient

## Available Nodes (confirmed v0.12.3)
LayerDiffusion, RMBG-2.0, VACE 14B, JuggernautXL, DreamShaper, Flux, nomic-embed-text
All 11 custom nodes verified working.
