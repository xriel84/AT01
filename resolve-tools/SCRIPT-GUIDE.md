# EdBot Script Guide

## What EdBot Does
EdBot turns long recordings (livestreams, talks, workshops) into
platform-ready social media clips automatically. It handles:
- Finding the good parts (transcription + AI analysis)
- Cutting out silence and dead air
- Reframing for each platform (portrait, square, landscape)
- Adding subtitles
- Rendering to spec

## Script Map

### Scripts That Talk to Resolve (need Resolve running)
These use DaVinci Resolve's Python API. Resolve must be open.

| Script | What It Does | One-Click Wrapper |
|--------|-------------|-------------------|
| resolve_ingest.py | Drops footage into Resolve, validates format, organizes by scene | run_ingest.ps1 |
| resolve_scope.py | Lists scenes, builds timelines, manages clip triage | run_scope_list.ps1 |
| edbot.py | Assembles clips per platform, applies SmartReframe, renders | Run-EdBot.ps1 |

**SmartReframe** is Resolve's AI feature that reframes landscape video
to portrait/square by tracking the subject. It's the key reason we use
Resolve Studio ($295) instead of free tools.

**Hard rules for Resolve scripts:**
- Must `cd` to Resolve install dir before running
- Must use `py -3.12` (ABI lock with fusionscript.dll)
- Must set `Scaling=3` (FILL) before SmartReframe to prevent black bars
- SmartReframe returns None on landscape-to-landscape -- script catches this

### Scripts That Don't Need Resolve
These use FFmpeg, faster-whisper, or auto-editor. No Resolve required.

| Script | What It Does | Depends On |
|--------|-------------|------------|
| footage_match.py | Groups related footage files by name patterns and timestamps | None (stdlib only) |
| shot_align.py | Aligns multi-camera recordings by transcript or audio fingerprint | faster-whisper, librosa |
| nb10_silence_remove.py | Batch removes silence from clips | auto-editor (pip) |
| nb10_subtitle_gen.py | Generates .ass subtitle files from audio | faster-whisper (GPU) |
| nb10_subtitle_burn.py | Burns subtitles into video | FFmpeg + libass |
| nb10_visual_filter.py | Checks if a person is in frame (rejects empty shots) | YOLOv8 (GPU) |
| nb10_supercut_pipeline.py | Full pipeline orchestrator (all stages) | Everything above |

### Support Scripts

| Script | What It Does |
|--------|-------------|
| resolve_common.py | Shared helpers (Resolve connection, path setup, logging) |
| NB10VIDEO-Validate.ps1 | Checks rendered output against platform specs |

## The 8-Stage Pipeline

```
1. TRANSCRIPTION      faster-whisper -> timestamped transcript
2. HIGHLIGHT ANALYSIS  Ollama -> ranked clip candidates
3. VISUAL FILTERING    YOLOv8 -> reject empty-room clips
4. CLIP EXTRACTION     FFmpeg -> individual clip files
5. SILENCE REMOVAL     auto-editor -> cut dead air
6. RESOLVE ASSEMBLY    Resolve API -> per-platform timelines + SmartReframe
7. SUBTITLE GENERATION faster-whisper -> .ass files with word timing
8. SUBTITLE BURN-IN    FFmpeg libass -> final captioned clips
```

Stages 1-4 proven. Stage 5 designed. Stage 6 partial (3/5 platforms).
Stages 7-8 designed but not built.

## Platform Specs

| Platform | Aspect | Resolution | Max Length | Codec |
|----------|--------|-----------|-----------|-------|
| TikTok | 9:16 | 1080x1920 | 60s | H.264 |
| Instagram Reels | 9:16 | 1080x1920 | 90s | H.264 |
| YouTube Shorts | 9:16 | 1080x1920 | 60s | H.264 |
| YouTube | 16:9 | 1920x1080 | 10min | H.264 |
| LinkedIn | 16:9 or 1:1 | 1920x1080 or 1080x1080 | 120s | H.264 |

All: 30fps, AAC audio 48kHz 192kbps, 15-20 Mbps video bitrate.

## GPU Rules
Only ONE GPU task at a time (single RTX A6000):
- faster-whisper (~10GB VRAM)
- Ollama mistral-nemo (~5GB VRAM)
- YOLOv8 (~2GB VRAM)
- Resolve SmartReframe (variable)
- FFmpeg h264_nvenc (minimal)

Never run two GPU tasks simultaneously.
