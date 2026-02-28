# Transcript → Chapter Pipeline — YD Guide

**For:** Yidan (AgileLens/edbot, AL branch)
**Date:** 2026-02-27
**Server:** `localhost:8901` (EdBot FastAPI)

---

## What This Pipeline Does

You feed it video files and it produces searchable transcripts with chapter boundaries, silence maps, and speaker labels. The output JSON files are what the viewer frontend consumes to let you navigate any topic across your videos. All tools run via the same FastAPI server on port 8901.

---

## Quick Start — Process a Video End to End

Make sure the server is running first:

```powershell
cd C:\agile-lens\edbot
py -3.12 -m uvicorn agents.edbot.server:app --port 8901
```

Then process a video in 4 steps:

```bash
# 1. Transcribe the video → produces chunks + word timestamps
curl -X POST http://127.0.0.1:8901/api/transcribe \
  -H "Content-Type: application/json" \
  -d '{"input_path": "C:/agile-lens/edbot/test_videos/agile_test.MOV", "output_dir": "output"}'

# 2. Detect silence gaps → produces silence map
curl -X POST http://127.0.0.1:8901/api/silence \
  -H "Content-Type: application/json" \
  -d '{"input_path": "C:/agile-lens/edbot/test_videos/agile_test.MOV", "output_dir": "output"}'

# 3. Detect chapters → uses cached chunks + silence map
curl http://127.0.0.1:8901/api/chapters

# 4. Search across transcripts
curl -X POST http://127.0.0.1:8901/api/search-transcripts \
  -H "Content-Type: application/json" \
  -d '{"query": "agile sprint"}'
```

Done. You now have chunks, silence map, chapters, and a searchable index.

---

## Tool Reference

### 1. transcribe.py — Video Transcription

**What it does:** Extracts audio from video, runs faster-whisper speech-to-text, and buckets word-level timestamps into 10-second chunks.

**Function:**
```python
def transcribe_video(
    video_path: str,
    output_dir: str | None = None,
    model_size: str | None = None,     # "small", "medium", "large-v3" (auto-detect)
    compute_type: str | None = None,   # "int8", "float16" (auto-detect)
    device: str | None = None,         # "cuda", "cpu" (auto-detect)
) -> dict[str, Any]
```

**Input:** Path to any video file (.mp4, .mov, .mkv, .avi, .webm). Files >3 min are auto-chunked into 90s segments with 5s overlap for faster processing.

**Endpoint:** `POST /api/transcribe`

**Request body:**
```json
{
  "input_path": "C:/path/to/video.MOV",
  "output_dir": "output",
  "model_size": null,
  "compute_type": null,
  "device": null
}
```

**Example curl:**
```bash
curl -X POST http://127.0.0.1:8901/api/transcribe \
  -H "Content-Type: application/json" \
  -d '{"input_path": "C:/agile-lens/edbot/test_videos/agile_test.MOV", "output_dir": "output"}'
```

**Output JSON:**
```json
{
  "source": "agile_test.MOV",
  "duration": 39.2,
  "chunks": [
    {
      "id": 0,
      "start": 0.0,
      "end": 10.0,
      "text": "welcome to the sprint review today we will go over",
      "word_count": 10,
      "silence_ratio": 0.35,
      "has_speech": true
    },
    {
      "id": 1,
      "start": 10.0,
      "end": 20.0,
      "text": "the backlog items that were completed this week",
      "word_count": 8,
      "silence_ratio": 0.42,
      "has_speech": true
    }
  ],
  "word_count": 18,
  "config_used": {
    "model_size": "medium",
    "compute_type": "int8",
    "device": "cuda"
  },
  "chunked": false
}
```

**Files written:** `output/chunks.json`, `output/transcript.json`

**GPU:** Yes — your RTX 4080 runs `medium` model with `int8` compute. CPU fallback (`small`/`int8`/`cpu`) available if GPU fails. Fallback chain: large-v3/float16 → large-v3/int8 → medium/int8 → small/cpu.

**Speed:** ~5-15s for a 1-minute video on your 4080. Longer videos auto-chunk for parallel processing.

---

### 2. chapter_detect.py — Chapter Detection

**What it does:** Identifies chapter boundaries from silence gaps or high-silence chunks, then merges short chapters to enforce a minimum duration. CPU-only — no GPU dependency.

**Function:**
```python
def detect_chapters(
    chunks: list[dict],                          # from transcribe_video
    silence_map: dict | None = None,             # from detect_silence (optional)
    duration: float | None = None,               # total seconds (auto-inferred)
    min_chapter_duration: float = 30.0,          # minimum chapter length
    silence_gap_threshold: float = 2.0,          # gap seconds to split chapters
) -> list[dict]
```

**Input:** Chunks list (from transcription) + optional silence map. Does NOT take a video file directly — requires transcription output first.

**Endpoint:** `GET /api/chapters`

No request body needed — uses cached session data from prior `/api/transcribe` and `/api/silence` calls.

**Example curl:**
```bash
curl http://127.0.0.1:8901/api/chapters
```

**Output JSON:**
```json
{
  "chapters": [
    {
      "chapter_id": 0,
      "start": 0.0,
      "end": 50.0,
      "duration": 50.0,
      "chunk_ids": [0, 1, 2, 3, 4],
      "title": "welcome to the sprint review today"
    },
    {
      "chapter_id": 1,
      "start": 50.0,
      "end": 100.0,
      "duration": 50.0,
      "chunk_ids": [5, 6, 7, 8, 9],
      "title": "next up the design updates from"
    }
  ]
}
```

**GPU:** None required. Pure Python, CPU-only. Runs on any machine.

**How boundaries are found:**
1. If silence_map provided: gaps >= `silence_gap_threshold` seconds become boundaries
2. If no silence_map: chunks with `silence_ratio > 0.8` become boundaries
3. Short chapters (< `min_chapter_duration`) merge into neighbors
4. Titles auto-generated from first 8 words of first speech chunk

---

### 3. silence_detect.py — Silence Detection

**What it does:** Runs FFmpeg's `silencedetect` filter on video audio, parses the output, and builds a silence map with gaps, speech segments (inverse of gaps), and stats.

**Function:**
```python
def detect_silence(
    video_path: str,
    threshold_db: float = -50.0,     # silence threshold in dB
    min_duration: float = 0.5,       # minimum silence duration in seconds
    output_dir: str | None = None,
) -> dict[str, Any]
```

**Input:** Path to video file. Works directly on the video — extracts audio internally via FFmpeg.

**Endpoint:** `POST /api/silence`

**Request body:**
```json
{
  "input_path": "C:/path/to/video.MOV",
  "output_dir": "output"
}
```

**Example curl:**
```bash
curl -X POST http://127.0.0.1:8901/api/silence \
  -H "Content-Type: application/json" \
  -d '{"input_path": "C:/agile-lens/edbot/test_videos/agile_test.MOV", "output_dir": "output"}'
```

**Output JSON:**
```json
{
  "source": "agile_test.MOV",
  "duration": 39.2,
  "threshold_db": -50.0,
  "gaps": [
    {"start": 5.2, "end": 7.8, "duration": 2.6},
    {"start": 18.1, "end": 19.5, "duration": 1.4}
  ],
  "speech": [
    {"start": 0.0, "end": 5.2, "duration": 5.2},
    {"start": 7.8, "end": 18.1, "duration": 10.3},
    {"start": 19.5, "end": 39.2, "duration": 19.7}
  ],
  "stats": {
    "total_silence": 4.0,
    "total_speech": 35.2,
    "silence_percentage": 10.2,
    "gap_count": 2
  }
}
```

**File written:** `output/silence_map.json`

**GPU:** None required. FFmpeg silencedetect is CPU-only.

---

### 4. transcript_index.py — Transcript Search

**What it does:** Builds an inverted word index across all transcribed videos. Supports keyword search with partial matching and optional spaCy NER entity extraction.

**Functions:**
```python
def build_index(manifest: dict, output_dir: str = "temp") -> dict[str, Any]
def auto_build_index(output_dir: str = "temp") -> dict[str, Any] | None
def search_index(index: dict, query: str, max_results: int = 20) -> list[dict]
```

**Input:** `build_index` takes a batch manifest + directory with `*_chunks.json` files. `auto_build_index` scans the temp directory automatically. `search_index` takes the index dict and a query string.

**Endpoints:**

| Method | Path | Description |
|--------|------|-------------|
| `GET`  | `/api/transcript-index` | Return existing index |
| `POST` | `/api/build-index` | Build/rebuild index from chunk files |
| `POST` | `/api/search-transcripts` | Search with auto-build |

**Search request body:**
```json
{
  "query": "sprint review",
  "max_results": 20
}
```

**Example curl:**
```bash
# Build index
curl -X POST http://127.0.0.1:8901/api/build-index

# Search
curl -X POST http://127.0.0.1:8901/api/search-transcripts \
  -H "Content-Type: application/json" \
  -d '{"query": "sprint review"}'
```

**Search output JSON:**
```json
{
  "query": "sprint review",
  "results": [
    {
      "file": 0,
      "chunk": 2,
      "start": 20.0,
      "match_type": "word",
      "chunk_text": "we completed the sprint review items for this week",
      "filename": "team-meeting-2026-02-15.mov"
    }
  ],
  "count": 1
}
```

**Build index output:**
```json
{
  "status": "ok",
  "files_indexed": 3,
  "word_count": 1500
}
```

**GPU:** None required. CPU-only. Optional spaCy NER (also CPU).

---

### 5. speaker_detect.py — Speaker Detection

**What it does:** Detects speaker changes in audio using energy-based heuristic (always works, stdlib only) or optional pyannote.audio for real diarization.

**Function:**
```python
def detect_speakers(
    audio_path: str,
    chunks: list[dict] | None = None,      # chunk dicts from transcription
    method: str = "energy",                 # "energy" or "pyannote"
    num_speakers: int | None = None,        # expected speaker count hint
    output_dir: str | None = None,
) -> dict
```

**Input:** Path to audio/video file + optional chunks for per-chunk speaker assignment.

**Endpoint:** `GET /api/speakers`

No request body — uses cached session video path and chunks from prior `/api/transcribe` call.

**Example curl:**
```bash
# Run speaker detection
curl http://127.0.0.1:8901/api/speakers

# Label speakers with real names
curl -X POST http://127.0.0.1:8901/api/label_speakers \
  -H "Content-Type: application/json" \
  -d '{"labels": {"SPEAKER_0": "Ari", "SPEAKER_1": "Alex"}}'
```

**Output JSON:**
```json
{
  "source": "agile_test.MOV",
  "method": "energy",
  "speakers": ["SPEAKER_0", "SPEAKER_1"],
  "segments": [
    {"start": 0.0, "end": 30.0, "speaker": "SPEAKER_0"},
    {"start": 30.0, "end": 60.0, "speaker": "SPEAKER_1"}
  ],
  "chunk_speakers": {
    "0": "SPEAKER_0",
    "1": "SPEAKER_0",
    "2": "SPEAKER_0",
    "3": "SPEAKER_1"
  }
}
```

**File written:** `output/speaker_map.json`

**GPU:** Energy method = CPU-only (default). Pyannote method = GPU-accelerated (your 4080 supports it if pyannote is installed with HF_TOKEN set).

---

### 6. video_prober.py — Video Metadata Probe

**What it does:** Extracts structured metadata from video files via ffprobe: duration, resolution, codec, bitrate, FPS, audio channels, file size.

**Function:**
```python
def probe_video(video_path: str) -> dict[str, Any]
def scan_local_dir(directory: str, recursive: bool = True) -> dict[str, Any]
```

**Input:** Path to a video file, or a directory to scan all videos within.

**Endpoint:** `POST /api/probe`

**Request body:**
```json
{
  "video_path": "C:/path/to/video.MOV"
}
```

**Example curl:**
```bash
curl -X POST http://127.0.0.1:8901/api/probe \
  -H "Content-Type: application/json" \
  -d '{"video_path": "C:/agile-lens/edbot/test_videos/agile_test.MOV"}'
```

**Output JSON:**
```json
{
  "path": "C:/agile-lens/edbot/test_videos/agile_test.MOV",
  "filename": "agile_test.MOV",
  "duration_sec": 39.2,
  "width": 1920,
  "height": 1080,
  "fps": 23.976,
  "video_codec": "h264",
  "audio_codec": "aac",
  "bitrate_kbps": 8500,
  "audio_channels": 2,
  "file_size_mb": 42.5,
  "format_name": "mov,mp4,m4a,3gp,3g2,mj2"
}
```

**GPU:** None required. FFprobe is CPU-only.

---

### 7. manifest_writer.py — Output Manifest Builder

**What it does:** Converts pipeline outputs (video probes, chunks, transcripts) into two JSON formats: `raptor-library.json` (full video entries with transcripts + metadata) and `assembly_manifest.json` (short clips with platform/aspect info).

**Functions:**
```python
def to_raptor_entry(video_probe, chunks, transcript_words, ...) -> dict
def to_assembly_clip(chunk, source_id, platform, aspect, ...) -> dict
def write_raptor_library(entries, output_path, source_root) -> dict
def write_assembly_manifest(clips, output_path, source_clip) -> dict
def sync_all(video_dir, output_dir, chunks_dir) -> dict
```

**Endpoints:**

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/manifest/sync` | Scan + generate both manifests |
| `POST` | `/api/manifest/raptor-library` | Generate raptor-library for one video |
| `POST` | `/api/manifest/assembly` | Generate assembly manifest from cached chunks |

**Example curl (full sync):**
```bash
curl -X POST http://127.0.0.1:8901/api/manifest/sync \
  -H "Content-Type: application/json" \
  -d '{"video_dir": "C:/agile-lens/edbot/test_videos", "output_dir": "output"}'
```

**raptor-library.json entry structure:**
```json
{
  "id": "RH_a1b2c3d4e5f6",
  "two_word_name": "Agile Test",
  "filename": "agile_test.MOV",
  "relative_path": "agile_test.MOV",
  "duration_sec": 39.2,
  "resolution": "1920x1080",
  "has_audio": true,
  "transcript_full": "welcome to the sprint review today...",
  "transcript_snippet": "welcome to the sprint review today...",
  "whisper_segments": [
    {"start": 0.0, "end": 2.5, "text": "welcome to the sprint"}
  ],
  "status": "transcribed",
  "file_hash": "a1b2c3d4e5f6"
}
```

**GPU:** None required. Pure Python JSON assembly.

---

## Output JSON Schemas

All files written to `output/` (or your specified `output_dir`):

| File | Written by | Contents |
|------|-----------|----------|
| `chunks.json` | transcribe | 10-second chunks with text, word_count, silence_ratio |
| `transcript.json` | transcribe | Word-level timestamps: `[{"word": "hello", "start": 0.5, "end": 0.8}]` |
| `silence_map.json` | silence_detect | Gaps, speech segments, stats |
| `speaker_map.json` | speaker_detect | Speaker segments + per-chunk speaker labels |
| `raptor-library.json` | manifest_writer | Master index of all videos with transcripts |
| `assembly_manifest.json` | manifest_writer | Short clips for platform export |
| `transcript_index.json` | transcript_index | Inverted word index for search (written to `temp/`) |

---

## How These Tools Chain Together

```
video file
    │
    ├──→ transcribe ──→ chunks.json + transcript.json
    │                        │
    │                        ├──→ chapter_detect ──→ chapters (JSON response)
    │                        │
    │                        ├──→ search_index ──→ search results
    │                        │
    │                        └──→ speaker_detect ──→ speaker_map.json
    │
    ├──→ silence_detect ──→ silence_map.json
    │                          │
    │                          └──→ (feeds into chapter_detect for better boundaries)
    │
    ├──→ video_prober ──→ probe metadata (duration, codec, resolution)
    │
    └──→ manifest_writer.sync_all ──→ raptor-library.json + assembly_manifest.json
              (combines probes + chunks + transcripts into master index)
```

**Minimum path** (3 calls to get chapters):
1. `POST /api/transcribe` — produces chunks
2. `POST /api/silence` — produces silence map (improves chapter boundaries)
3. `GET /api/chapters` — produces chapters from cached data

**Full pipeline** (all data for the viewer):
1. `POST /api/transcribe` — chunks + transcript
2. `POST /api/silence` — silence map
3. `GET /api/chapters` — chapter boundaries
4. `GET /api/speakers` — speaker labels
5. `POST /api/search-transcripts` — verify search works
6. `POST /api/manifest/sync` — master index files

---

## P3 Test Procedure — chapter_detect

This is your next verification target. Chapter detection is CPU-only — no GPU setup needed.

### Prerequisites

Server must be running:
```powershell
py -3.12 -m uvicorn agents.edbot.server:app --port 8901
```

### Step 1: Transcribe a test video

You already did this in P1. Run it again to populate the session:

```bash
curl -X POST http://127.0.0.1:8901/api/transcribe \
  -H "Content-Type: application/json" \
  -d '{"input_path": "C:/agile-lens/edbot/test_videos/agile_test.MOV", "output_dir": "output"}'
```

Expected: 200 OK, chunks in response.

### Step 2: Run silence detection

```bash
curl -X POST http://127.0.0.1:8901/api/silence \
  -H "Content-Type: application/json" \
  -d '{"input_path": "C:/agile-lens/edbot/test_videos/agile_test.MOV", "output_dir": "output"}'
```

Expected: 200 OK, silence_map with gaps array.

### Step 3: Run chapter detection

```bash
curl http://127.0.0.1:8901/api/chapters
```

Expected: 200 OK, JSON with `chapters` array. Each chapter has:
- `chapter_id` (int, sequential from 0)
- `start` / `end` (float, seconds)
- `duration` (float, seconds)
- `chunk_ids` (list of int)
- `title` (string, first ~8 words of speech)

### Step 4: Verify chapter output

Check:
- [ ] At least 1 chapter returned
- [ ] Timestamps are monotonically increasing
- [ ] All chunk IDs from transcription appear in exactly one chapter
- [ ] Titles contain recognizable words from the video
- [ ] `duration` = `end - start` for each chapter

### Step 5: Edge case — short video

Your `agile_test.MOV` is ~39 seconds. This IS the short video test.
Expected: 1-2 chapters max (the `min_chapter_duration` default is 30s).

### Step 6: Edge case — no silence gaps

If Step 2 returned zero gaps, Step 3 should still return at least 1 chapter
(falls back to chunk silence_ratio boundaries).

### Step 7: Run unit tests

```powershell
py -3.12 -m pytest tests/test_chapter_detect.py -v
```

Expected: 25 tests pass (23 synthetic + 2 real-data that skip if no test files).

### What PASS looks like

All steps return 200 OK. Chapters have valid structure. Unit tests pass.

### Report back

Write results to: `comms/from-yd/` on the AL branch.

Include for each test:
```
| Test | Endpoint | HTTP | Result | Notes |
|------|----------|------|--------|-------|
| P3-1 | POST /api/transcribe | 200 | PASS/FAIL | ... |
| P3-2 | POST /api/silence | 200 | PASS/FAIL | ... |
| P3-3 | GET /api/chapters | 200 | PASS/FAIL | ... |
| P3-4 | (edge: short video) | - | PASS/FAIL | ... |
| P3-5 | (edge: no gaps) | - | PASS/FAIL | ... |
| P3-6 | pytest unit tests | - | PASS/FAIL | X passed, Y skipped |
```

Commit with: `[yd] P3 test results — chapters + GPU framework`

---

## Your Hardware Profile

**Machine:** DESKTOP-BD76CV3 (RTX 4080 16GB) — **Tier 1**

**Config file:** `configs/gpu_capabilities_stran.json`

| Tool | GPU? | Your Tier 1 Setting |
|------|------|-------------------|
| transcribe | Yes | medium / int8 / cuda |
| chapter_detect | No | CPU-only (rule-based) |
| silence_detect | No | CPU-only (FFmpeg) |
| transcript_index | No | CPU-only |
| speaker_detect | Energy=No, Pyannote=Yes | Energy default (CPU), pyannote optional (GPU) |
| video_prober | No | CPU-only (ffprobe) |
| manifest_writer | No | CPU-only |

**Whisper model on your hardware:** `medium` with `int8` compute type. Auto-detected from `gpu_capabilities_stran.json`. If GPU fails, falls back to `small`/`cpu` automatically.

**Task routing:** See `configs/task_routing.json` for the full tier map across all 34 tools.

---

## Troubleshooting

**Server not running:**
```
curl: (7) Failed to connect to 127.0.0.1 port 8901
```
Fix: Start the server with `py -3.12 -m uvicorn agents.edbot.server:app --port 8901`

**Wrong Python version:**
```
ModuleNotFoundError: No module named 'faster_whisper'
```
Fix: Use `py -3.12` — never bare `python` or `py`. All dependencies are installed under 3.12.

**No chunks cached (chapter_detect fails):**
```json
{"detail": {"error": "no chunks — run /api/transcribe first", "code": "NO_TRANSCRIPT"}}
```
Fix: Run `/api/transcribe` first. Chapter detection needs transcription output cached in memory.

**GPU out of memory:**
Transcription auto-falls back: `large-v3/float16` → `large-v3/int8` → `medium/int8` → `small/cpu`. If your 4080 runs out of VRAM, it will automatically try a smaller model. No action needed.

**FFmpeg not found:**
```
FileNotFoundError: [WinError 2] The system cannot find the file specified
```
Fix: Ensure FFmpeg is on your PATH. Test with `ffmpeg -version` in PowerShell.

**Silence detection finds zero gaps:**
This is normal for some videos (continuous speech). Chapter detection handles this by falling back to chunk silence_ratio boundaries. At least 1 chapter will always be returned.

**Search returns empty results:**
```json
{"query": "something", "results": [], "count": 0}
```
Fix: Build the index first with `POST /api/build-index`, or ensure you've run transcription so chunk files exist in `temp/`.
