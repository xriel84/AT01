# ArtBot -- API Surface & Pipeline Spec

**Agent:** ArtBot (asset generation + review pipeline)
**Repo:** AT01 (xriel84/AT01)
**Location:** `agents/artbot/`
**Runtime:** `py -3.12` -- never bare `python`
**Isolation:** ArtBot source lives ONLY in AT01. Never auto-syncs to agile-lens or edbot-collab.

---

## 1. Pipeline Flow

```
HUMAN BRIEF
  |  "animated logo", "PNG frame for intro", natural language
  v
brief.py           parse NLP -> ask leading questions -> build SDXL prompt
  |                uses sdxl_library.json for NLP-to-SDXL translation
  v
generate.py        submit N prompt variations to ComfyUI API (SDXL/LayerDiff)
  |                slight setting tweaks per iteration (cfg, steps, seed)
  v
REVIEW UI          JP designs the interface; ArtBot outputs JSON manifest
  |
  v
TIER 1 GATE        AT or YD picks winners from test images
  |                human decides per image: animate? or static -> EdBot directly
  v
animate.py         ComfyUI VACE / AnimateDiff (512x512 ONLY -- OOM at 1024)
  |                only runs on images marked "animate" at Tier 1
  v
TIER 2 GATE        review animated versions (approve / reject / redo)
  |
  v
label.py           tag + rename per AT taxonomy -> hand off to EdBot
  |                naming: {project}_{subject}_{shot}_{action}_{seq}.{ext}
  v
TIER 3 GATE        full clip review in #ai-workspace
  |
  v
promote.py         approved assets -> #ai-marketing-interface
```

**Animation is optional.** The human designates at Tier 1 whether each image
should be animated or sent static directly to EdBot. Not every asset goes
through animate.py.

---

## 2. Tier Gate Definitions

### Tier 1 -- Image Selection

| Aspect       | Detail |
|--------------|--------|
| **Input**    | N generated image variants from ComfyUI |
| **Reviewer** | AT or YD (human) |
| **Criteria** | Style match (noir/gold palette, bold outlines), correct framing, transparency quality, subject clarity |
| **Pass**     | At least 1 winner selected per brief |
| **Output**   | Selected images marked `animate` or `static`; rejects logged |
| **Channel**  | Review UI (localhost, JP-designed) |

### Tier 2 -- Animation Review

| Aspect       | Detail |
|--------------|--------|
| **Input**    | Animated WebP/MP4 from VACE/AnimateDiff |
| **Reviewer** | AT or YD (human) |
| **Criteria** | Motion quality, loop continuity, no artifacts, matches original still intent |
| **Pass**     | Approved animation OR fallback to static version |
| **Output**   | Approved animated files ready for labeling |
| **Channel**  | Review UI |

### Tier 3 -- Final Clip Review

| Aspect       | Detail |
|--------------|--------|
| **Input**    | Labeled, taxonomy-compliant assets (still + animated) |
| **Reviewer** | Team review in #ai-workspace |
| **Criteria** | Production-ready quality, correct naming, manifest accuracy |
| **Pass**     | Asset promoted to #ai-marketing-interface |
| **Output**   | Promotion log entry; asset available to EdBot and downstream |
| **Channel**  | #ai-workspace Slack channel |

---

## 3. Callable Interface

### brief.py -- NLP to SDXL Prompt Conversion

```python
def parse_brief(text: str) -> dict:
    """Parse a human brief into structured fields.

    Args:
        text: Natural language description, e.g. "animated logo spinning gold"

    Returns:
        dict with keys: subject, action, style_hints, format, dimensions
    """

def build_prompt(brief: dict, library: dict) -> str:
    """Convert structured brief into SDXL prompt string.

    Args:
        brief: Output of parse_brief()
        library: sdxl_library.json contents (NLP->SDXL term mapping)

    Returns:
        SDXL-ready positive prompt string with style tokens, quality tokens, etc.
    """

def generate_variations(base_prompt: str, n: int = 3) -> list[dict]:
    """Generate N prompt variations with slight tweaks.

    Args:
        base_prompt: Output of build_prompt()
        n: Number of variations (default 3)

    Returns:
        List of dicts, each with keys: prompt, cfg_scale, steps, seed
    """
```

### generate.py -- ComfyUI Batch Generation

```python
def build_workflow(prompt: str, settings: dict) -> dict:
    """Build a ComfyUI workflow JSON from prompt and settings.

    Args:
        prompt: SDXL prompt string
        settings: Dict with cfg_scale, steps, seed, width, height,
                  filename_prefix, negative_prompt, checkpoint

    Returns:
        Complete ComfyUI workflow dict ready for /prompt endpoint
    """

def submit_batch(workflows: list[dict], server: str = "http://127.0.0.1:8188") -> list[dict]:
    """Submit a batch of workflows to ComfyUI API.

    Args:
        workflows: List of workflow dicts from build_workflow()
        server: ComfyUI server URL

    Returns:
        List of dicts with prompt_id, status per submission.
        Waits 5s between submissions per batch protocol.
    """

def collect_results(
    prompt_ids: list[str],
    server: str = "http://127.0.0.1:8188",
    timeout: int = 300
) -> list[Path]:
    """Poll ComfyUI for completed outputs.

    Args:
        prompt_ids: List of prompt IDs from submit_batch()
        server: ComfyUI server URL
        timeout: Max seconds to wait for all results

    Returns:
        List of Paths to generated image files on disk
    """
```

### review.py -- Review Manifest Management

```python
def build_review_manifest(
    images: list[Path],
    brief: dict,
    tier: int
) -> dict:
    """Build a JSON manifest for the review UI.

    Args:
        images: Paths to generated images
        brief: Original parsed brief for context
        tier: Gate tier (1, 2, or 3)

    Returns:
        Dict with: tier, brief_summary, candidates (list of
        {path, thumbnail_url, dimensions, file_size_kb, score})
    """

def mark_selection(
    manifest: dict,
    selected: list[int],
    animate: dict[int, bool]
) -> dict:
    """Record human selections on a review manifest.

    Args:
        manifest: Output of build_review_manifest()
        selected: Indices of winning candidates (0-based)
        animate: Map of index -> bool (True=animate, False=static)

    Returns:
        Updated manifest with selection metadata and next-step routing
    """
```

### animate.py -- VACE/AnimateDiff Pipeline

```python
def build_animate_workflow(image_path: Path, settings: dict) -> dict:
    """Build a ComfyUI VACE or AnimateDiff workflow for an image.

    Args:
        image_path: Path to the source still image
        settings: Dict with motion_type, frames, fps, loop.
                  Resolution MUST be 512x512 (OOM at 1024).

    Returns:
        Complete ComfyUI workflow dict for animation
    """

def animate_batch(
    manifest: dict,
    server: str = "http://127.0.0.1:8188"
) -> list[dict]:
    """Submit animation jobs for all selected images in a manifest.

    Args:
        manifest: Review manifest with selections marked animate=True
        server: ComfyUI server URL

    Returns:
        List of dicts with prompt_id, source_image, status per submission
    """
```

### label.py -- Taxonomy Tagging & Rename

```python
def build_label(
    project: str,
    subject: str,
    shot: str,
    action: str,
    seq: str = "00001"
) -> str:
    """Build a filename per NB11-COMFYUI-AGENT-PROTOCOL naming convention.

    Args:
        project: Project prefix (e.g. "at", "nb10")
        subject: Subject token (e.g. "aribot", "skyline")
        shot: Shot grid position (e.g. "M-C", "W-L", "C-C")
        action: Action token (e.g. "idle", "work", "loop")
        seq: Sequence number, zero-padded 5 digits (default "00001")

    Returns:
        Filename string: "{project}_{subject}_{shot}_{action}_{seq}"
        (extension added separately)
    """

def rename_for_edbot(
    manifest: dict,
    output_dir: Path,
    project: str = "at"
) -> list[Path]:
    """Rename and move approved assets to taxonomy-compliant names.

    Args:
        manifest: Review manifest with approved selections
        output_dir: Target directory for renamed files
        project: Project prefix for naming

    Returns:
        List of new Paths after rename/move. Ready for EdBot handoff.
    """
```

### promote.py -- Tier Advancement & Logging

```python
def advance(file_path: Path, current_tier: int, base_dir: Path) -> Path:
    """Move an asset from one tier directory to the next.

    Args:
        file_path: Current file location
        current_tier: Current tier (1, 2, or 3)
        base_dir: Pipeline base directory

    Returns:
        New Path in the next tier's directory.
        Tier 3 approval moves to delivery zone.
    """

def log_promotion(
    log_path: Path,
    file_name: str,
    from_tier: int,
    to_tier: int
) -> None:
    """Append a promotion event to the pipeline log.

    Args:
        log_path: Path to the JSON log file
        file_name: Asset filename being promoted
        from_tier: Source tier number
        to_tier: Destination tier number

    Side effects:
        Appends entry with timestamp, file_name, from_tier, to_tier
        to the log file. Creates file if it does not exist.
    """
```

---

## 4. Naming Convention

All assets follow the NB11-COMFYUI-AGENT-PROTOCOL schema:

```
{project}_{subject}_{shot}_{action}_{seq}.{ext}
```

| Token     | Example Values                  | Required   |
|-----------|---------------------------------|------------|
| project   | `at`, `nb10`, `nb11`           | Yes        |
| subject   | `aribot`, `kevin`, `skyline`   | Yes        |
| shot      | `W-L`, `M-C`, `C-C`           | When spatial |
| action    | `idle`, `work`, `loop`, `still`| Yes        |
| seq       | `00001`, `f01of06`             | When multiple |
| ext       | `.png`, `.webp`, `.mp4`        | Yes        |

**ComfyUI Save node prefix:** `at/at_{subject}_{shot}_{action}`
ComfyUI auto-appends `_00001`, `_00002`, etc.

**Video platform extensions:** Append platform token before seq for video outputs:
`{project}_{subject}_{shot}_{action}_{platform}_{seq}.{ext}`
Platforms: `tk` (TikTok), `ig` (Instagram), `yt` (YouTube), `li` (LinkedIn), `sh` (Shorts), `raw` (source).

See `C:\NB11\agile-lens\NB11-COMFYUI-AGENT-PROTOCOL.md` for the full specification
including shot grid, stage mode prefixes, and migration scripts.

---

## 5. SDXL Prompt Library

**File:** `agents/artbot/prompts/sdxl_library.json` (to be built)

**Purpose:** Knowledge base that maps natural language terms to SDXL-optimized
prompt tokens. brief.py consults this library when converting a human brief
into a generation-ready prompt.

**Structure:**

```json
{
  "style": {
    "noir": "1930s art deco style, Dick Tracy cartoon aesthetic, flat bold colors, heavy black outlines, geometric shapes, noir lighting, vintage animation cel",
    "gold": "gold metallic accents, art deco gold trim, warm amber highlights",
    "clean": "clean vector art, sharp edges, solid fills, no gradients"
  },
  "quality": {
    "high": "masterpiece, best quality, highly detailed",
    "production": "production quality, professional illustration, print ready"
  },
  "negative": {
    "default": "photorealistic, 3d render, anime, modern, gradient shading, soft edges, blurry, watermark, text, signature, photograph, realistic skin texture"
  },
  "subjects": {
    "aribot": "cartoon robot character, round head, single eye, metallic body",
    "desk": "office desk, computer monitor, keyboard, papers, coffee cup",
    "skyline": "art deco city skyline, noir cityscape, geometric buildings"
  },
  "framing": {
    "W": "full body, wide shot, full scene visible",
    "M": "medium shot, waist up, upper body",
    "C": "close up, head and shoulders, portrait crop"
  }
}
```

brief.py looks up terms from the human brief in this library, composes them
with the appropriate style/quality/negative tokens, and outputs a complete
SDXL prompt string. This keeps prompt engineering knowledge centralized and
version-controlled rather than scattered across workflow files.

---

## 6. Inter-Agent Communication

ArtBot uses the shared message bus defined in `agents/shared/schema.md`.

### Message Format

```json
{
  "id": "msg_NNN",
  "from": "artbot",
  "to": "edbot",
  "type": "FEEDBACK | REQUEST | REPORT",
  "timestamp": "2026-02-24T14:30:00Z",
  "subject": "Short description",
  "body": "Full message text. Markdown allowed.",
  "data": {},
  "status": "unread"
}
```

### Bus Files

| File                     | Writer  | Reader  | Purpose |
|--------------------------|---------|---------|---------|
| `artbot-to-edbot.json`  | ArtBot  | EdBot   | Asset handoff, labeled files ready for timeline |
| `edbot-to-artbot.json`  | EdBot   | ArtBot  | Revision requests, format/size requirements |
| `artbot-to-anabot.json` | ArtBot  | AnaBot  | Asset generation reports, variant stats |
| `anabot-to-artbot.json` | AnaBot  | ArtBot  | Performance feedback on asset engagement |

### Message Types

- **REPORT** (ArtBot -> EdBot): "3 approved assets labeled and ready for timeline import"
- **REQUEST** (EdBot -> ArtBot): "Need 16:9 variant of at_aribot_M-C_idle for YouTube intro"
- **FEEDBACK** (AnaBot -> ArtBot): "Gold palette assets get 2x engagement vs silver -- bias toward warm tones"

### Rules

1. Never delete messages. Append only.
2. Only the recipient changes `status` (unread -> read -> actioned).
3. The `data` field carries structured payloads -- keep `body` human-readable.
4. Message IDs are sequential per file. Check last ID before appending.
5. Always validate JSON after write. Corrupt bus = broken pipeline.

---

## 7. Slack Channel Mapping

| Channel                    | Purpose                              | Who posts          |
|----------------------------|--------------------------------------|---------------------|
| `#ai-workspace`           | All agent communication, Tier 3 review | ArtBot, EdBot, AnaBot |
| `#ai-marketing-interface` | Promoted approved materials          | ArtBot (via promote.py) |
| `#marketing`              | FINAL materials only, exec eyes      | Human only (AT)     |

**Flow:** Asset passes Tier 3 in #ai-workspace -> promote.py moves it to
#ai-marketing-interface -> AT manually promotes to #marketing after final
human review.

---

## 8. Isolation Rule

ArtBot source lives ONLY in AT01. It never auto-syncs to:
- `C:\NB11\agile-lens\` (Agile Lens demo -- separate project)
- `C:\NB11\worktrees\edbot-collab\` (shared EdBot collaboration repo)

ArtBot communicates with EdBot through the message bus (JSON files in
`agents/shared/`), not through shared source code. Generated assets move
through the tier gates and are delivered as files, not as code imports.

---

## 9. Directory Layout

```
agents/artbot/
  ARTBOT.md             <- this file
  brief.py              <- NLP -> SDXL prompt conversion
  generate.py           <- ComfyUI batch generation
  review.py             <- review manifest builder
  animate.py            <- VACE/AnimateDiff pipeline
  label.py              <- taxonomy tagging + rename
  promote.py            <- tier advancement + logging
  artbot.py             <- CLI entry point
  prompts/
    sdxl_library.json   <- NLP-to-SDXL prompt knowledge base
    .gitkeep
  tests/
    test_brief.py
    test_generate.py
    test_review.py
    test_animate.py
    test_label.py
    test_promote.py
    .gitkeep
```

---

## 10. Dependencies

- Python 3.12 (`py -3.12`)
- `requests` -- ComfyUI API calls
- `Pillow` -- image metadata inspection
- ComfyUI running locally at `http://127.0.0.1:8188`
- VACE workflow MUST use 512x512 resolution (OOM at 1024)
