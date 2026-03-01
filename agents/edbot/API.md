# EdBot API Reference

Base URL: `http://127.0.0.1:8901`

---

## Core Pipeline

### GET /api/health
Server health check and tool list.
**Response:** `{"status": "ok", "tools": ["transcribe", "silence_detect", ...]}`
```bash
curl http://127.0.0.1:8901/api/health
```

### GET /health
Alias for `/api/health`.
**Response:** `{"status": "ok", "tools": [...]}`
```bash
curl http://127.0.0.1:8901/health
```

### POST /api/transcribe
Transcribe a video file using faster-whisper.
**Request:** `{"input_path": "C:/AT01/input/video.mov", "output_dir": "output"}`
**Response:** `{"source": "video.mov", "duration": 300.0, "chunks": [{"id": 0, "start": 0.0, "end": 10.0, "text": "...", "word_count": 5, "silence_ratio": 0.1, "has_speech": true}, ...]}`
**Errors:** `400 FILE_NOT_FOUND` | `400 INVALID_INPUT` | `500 TOOL_ERROR`
```bash
curl -X POST http://127.0.0.1:8901/api/transcribe -H "Content-Type: application/json" -d "{\"input_path\": \"C:/AT01/input/video.mov\", \"output_dir\": \"output\"}"
```

### POST /api/silence
Detect silence gaps in a video file.
**Request:** `{"input_path": "C:/AT01/input/video.mov", "output_dir": "output"}`
**Response:** `{"source": "video.mov", "duration": 300.0, "threshold_db": -30.0, "gaps": [{"start": 10.0, "end": 20.0, "duration": 10.0}], "speech": [...], "stats": {"total_silence": 10.0, "total_speech": 290.0, "silence_percentage": 3.3, "gap_count": 1}}`
**Errors:** `500 TOOL_ERROR`
```bash
curl -X POST http://127.0.0.1:8901/api/silence -H "Content-Type: application/json" -d "{\"input_path\": \"C:/AT01/input/video.mov\"}"
```

### POST /api/parse
Parse a natural language command into an action dict.
**Request:** `{"text": "remove the silence", "input_path": "video.mov"}`
**Response:** `{"action": "silence_remove", "params": {...}, "executor": "ffmpeg", "confidence": 0.95}`
**Errors:** Returns `{"action": "unknown", "confidence": 0.0}` for unrecognized commands.
```bash
curl -X POST http://127.0.0.1:8901/api/parse -H "Content-Type: application/json" -d "{\"text\": \"remove the silence\"}"
```

### POST /api/execute
Execute an action dict (from /api/parse output).
**Request:** `{"action": {"action": "silence_remove", "params": {...}, "executor": "ffmpeg"}, "input_path": "video.mov"}`
**Response:** `{"status": "success", "action": "silence_remove", "input": "video.mov", "output": "output/video_silence_remove.mp4", "elapsed_seconds": 1.234, "error": null}`
**Errors:** `500 TOOL_ERROR`
```bash
curl -X POST http://127.0.0.1:8901/api/execute -H "Content-Type: application/json" -d "{\"action\": {\"action\": \"silence_remove\", \"params\": {}, \"executor\": \"ffmpeg\"}, \"input_path\": \"video.mov\"}"
```

### GET /api/chunks
Return last cached transcription result (from /api/transcribe).
**Response:** Same as /api/transcribe response.
**Errors:** `404 NO_TRANSCRIPT`
```bash
curl http://127.0.0.1:8901/api/chunks
```

### GET /api/silence_map
Return last cached silence map (from /api/silence).
**Response:** Same as /api/silence response.
**Errors:** `404 NO_SESSION`
```bash
curl http://127.0.0.1:8901/api/silence_map
```

### GET /api/outputs
Return output manifest from OutputWatcher.
**Response:** `{"watch_dir": "C:\\AT01\\output", "files": [{"filename": "video.mp4", "path": "C:\\AT01\\output\\video.mp4", "size_mb": 12.5}], "last_updated": "..."}`
```bash
curl http://127.0.0.1:8901/api/outputs
```

### GET /api/chapters
Run chapter detection on cached chunks + silence map.
**Response:** `{"chapters": [{"title": "Introduction", "start": 0.0, "end": 60.0, "summary": "..."}]}`
**Errors:** `400 NO_TRANSCRIPT`
```bash
curl http://127.0.0.1:8901/api/chapters
```

### GET /api/speakers
Run speaker detection on session video.
**Response:** `{"speakers": ["SPEAKER_0", "SPEAKER_1"], "segments": [{"speaker": "SPEAKER_0", "start": 0.0, "end": 15.0}], "chunk_speakers": {"0": "SPEAKER_0"}}`
**Errors:** `400 NO_SESSION` | `500 TOOL_ERROR`
```bash
curl http://127.0.0.1:8901/api/speakers
```

### POST /api/label_speakers
Update speaker labels in session.
**Request:** `{"labels": {"SPEAKER_0": "Ari", "SPEAKER_1": "Alex"}}`
**Response:** Updated speaker map with new labels applied.
**Errors:** `400 INVALID_INPUT` | `400 NO_SPEAKERS`
```bash
curl -X POST http://127.0.0.1:8901/api/label_speakers -H "Content-Type: application/json" -d "{\"labels\": {\"SPEAKER_0\": \"Ari\"}}"
```

### POST /api/portrait_crop
Crop a video to portrait (9:16) orientation.
**Request:** `{"input_path": "C:/AT01/input/video.mov", "output_dir": "output", "method": "center", "start": null, "end": null}`
**Response:** `{"status": "success", "output": "output/video_portrait.mp4", ...}`
**Errors:** `400 INVALID_INPUT` | `400 NO_SESSION` | `500 TOOL_ERROR`
```bash
curl -X POST http://127.0.0.1:8901/api/portrait_crop -H "Content-Type: application/json" -d "{\"input_path\": \"C:/AT01/input/video.mov\", \"method\": \"center\"}"
```

### POST /api/tiktok
Generate TikTok chunks from video.
**Request:** `{"input_path": "C:/AT01/input/video.mov", "output_dir": "output", "max_duration": 60.0, "crop_method": "center"}`
**Response:** `{"clips": [...], "count": 3, ...}`
**Errors:** `400 INVALID_INPUT` | `400 NO_SESSION` | `400 NO_TRANSCRIPT` | `500 TOOL_ERROR`
```bash
curl -X POST http://127.0.0.1:8901/api/tiktok -H "Content-Type: application/json" -d "{\"input_path\": \"C:/AT01/input/video.mov\"}"
```

### GET /api/session
Return current session state.
**Response:** `{"video_path": "C:/AT01/input/video.mov", "has_chunks": true, "has_silence_map": false, "has_chapters": false, "has_speaker_map": false, "has_clips_manifest": false}`
```bash
curl http://127.0.0.1:8901/api/session
```

### GET /api/clips_manifest
Return cached clips manifest (from /api/tiktok).
**Response:** Same as /api/tiktok response.
**Errors:** `400 NO_SESSION`
```bash
curl http://127.0.0.1:8901/api/clips_manifest
```

### GET /api/gpu_status
Check CUDA availability.
**Response:** `{"cuda_available": true, "device": "NVIDIA GeForce RTX 3060"}` or `{"cuda_available": false, "device": null}`
```bash
curl http://127.0.0.1:8901/api/gpu_status
```

---

## Search

### POST /api/batch-transcribe
Batch transcribe all videos in a directory.
**Request:** `{"input_dir": "C:/AT01/input"}`
**Response:** `{"files": [...], "count": 5, "manifest_path": "temp/batch_manifest.json"}`
**Errors:** `400 FILE_NOT_FOUND` | `500 TOOL_ERROR`
```bash
curl -X POST http://127.0.0.1:8901/api/batch-transcribe -H "Content-Type: application/json" -d "{\"input_dir\": \"C:/AT01/input\"}"
```

### POST /api/auto-name
Auto-name files from batch manifest.
**Request:** `{"manifest_path": "temp/batch_manifest.json"}`
**Response:** `{"renamed": [...], "count": 5}`
**Errors:** `400 FILE_NOT_FOUND` | `500 TOOL_ERROR`
```bash
curl -X POST http://127.0.0.1:8901/api/auto-name -H "Content-Type: application/json" -d "{\"manifest_path\": \"temp/batch_manifest.json\"}"
```

### POST /api/auto-chapter
Generate enhanced chapters with NLP titles.
**Request:** `{"video_path": "C:/AT01/input/video.mov"}`
**Response:** `{"chapters": [...], "video_path": "..."}`
**Errors:** `400 FILE_NOT_FOUND` | `500 TOOL_ERROR`
```bash
curl -X POST http://127.0.0.1:8901/api/auto-chapter -H "Content-Type: application/json" -d "{\"video_path\": \"C:/AT01/input/video.mov\"}"
```

### POST /api/build-index
Build or rebuild the transcript search index from chunk files in temp/.
**Response:** `{"status": "ok", "files_indexed": 3, "terms": 150}`
**Errors:** `404 NO_CHUNKS` | `500 TOOL_ERROR`
```bash
curl -X POST http://127.0.0.1:8901/api/build-index
```

### GET /api/transcript-index
Return transcript index.
**Response:** `{"files": [...], "terms": {...}}`
**Errors:** `404 NO_INDEX`
```bash
curl http://127.0.0.1:8901/api/transcript-index
```

### POST /api/search-transcripts
Search transcript index for query.
**Request:** `{"query": "hello world", "max_results": 20}`
**Response:** `{"query": "hello world", "results": [...], "count": 5}`
**Errors:** `404 NO_INDEX` | `500 TOOL_ERROR`
```bash
curl -X POST http://127.0.0.1:8901/api/search-transcripts -H "Content-Type: application/json" -d "{\"query\": \"hello world\"}"
```

### POST /api/match-shots
Find matching shots across transcribed videos.
**Request:** `{"similarity": 0.6}`
**Response:** `{"matches": [...], "count": 3}`
**Errors:** `400 NO_MANIFEST` | `500 TOOL_ERROR`
```bash
curl -X POST http://127.0.0.1:8901/api/match-shots -H "Content-Type: application/json" -d "{\"similarity\": 0.6}"
```

---

## Resolve

> Endpoints in this section require DaVinci Resolve Studio to be running.

### GET /api/resolve/status
Check if DaVinci Resolve is reachable.
**Response:** `{"available": true, "version": "20.3.1.6", "product": "DaVinci Resolve Studio", "error": null}`
```bash
curl http://127.0.0.1:8901/api/resolve/status
```

### POST /api/resolve/timeline
Create a Resolve timeline from a video file.
**Request:** `{"video_path": "C:/AT01/input/video.mov", "timeline_name": "my_timeline"}`
**Response:** `{"success": true, "timeline_name": "my_timeline", "error": null}`
**Errors:** `400 FILE_NOT_FOUND` | `500 TOOL_ERROR`
```bash
curl -X POST http://127.0.0.1:8901/api/resolve/timeline -H "Content-Type: application/json" -d "{\"video_path\": \"C:/AT01/input/video.mov\", \"timeline_name\": \"my_timeline\"}"
```

### POST /api/resolve/markers
Add chapter markers to a Resolve timeline.
**Request:** `{"chapters": [{"title": "Intro", "start": 0.0, "summary": "Introduction"}], "timeline_name": null, "fps": 24.0}`
**Response:** `{"success": true, "markers_added": 3, "error": null}`
**Errors:** `400 INVALID_INPUT` | `500 TOOL_ERROR`
```bash
curl -X POST http://127.0.0.1:8901/api/resolve/markers -H "Content-Type: application/json" -d "{\"chapters\": [{\"title\": \"Intro\", \"start\": 0.0}]}"
```

### POST /api/resolve/render
Start a Resolve render job.
**Request:** `{"timeline_name": "my_timeline", "output_path": "C:/AT01/output/render.mp4", "preset": "h264_mp4"}`
**Response:** `{"id": "a1b2c3d4", "status": "complete", "timeline": "my_timeline", "output_path": "...", "preset": "h264_mp4", "elapsed_seconds": 45.2, "error": null}`
**Presets:** `h264_mp4`, `h265_mp4`, `prores_mov`, `dnxhd_mxf`
**Errors:** `500 TOOL_ERROR`
```bash
curl -X POST http://127.0.0.1:8901/api/resolve/render -H "Content-Type: application/json" -d "{\"timeline_name\": \"my_timeline\", \"output_path\": \"C:/AT01/output/render.mp4\"}"
```

### GET /api/resolve/render/{job_id}
Get status of a Resolve render job.
**Response:** `{"id": "a1b2c3d4", "status": "complete", "timeline": "...", "output_path": "...", "elapsed_seconds": 45.2, "error": null}`
**Errors:** `404 NOT_FOUND`
```bash
curl http://127.0.0.1:8901/api/resolve/render/a1b2c3d4
```

### POST /api/resolve/command
Accept NLP command or structured decisions for Resolve execution. Supports two input paths: natural language command (translated via templates or Ollama) or pre-built decisions JSON. All modes: dry-run (default, safe), confirm (returns plan), execute (runs against Resolve).
**Body (NLP):** `{"command": "mark chapters as blue markers", "context": {"chapters": [...], "fps": 24}, "mode": "dry-run"}`
**Body (direct):** `{"decisions": {"generated_by": "...", "generated_at": "...", "fps": 24, "decisions": [...]}, "mode": "dry-run"}`
**Response:** `{"plan": {...}, "results": {"succeeded": 2, "failed": 0, "skipped": 0, "mode": "dry-run", "details": [...]}, "translation_method": "template", "mode": "dry-run"}`
**Errors:** `400 INVALID_INPUT` (empty request, invalid mode), `422 TRANSLATION_ERROR | VALIDATION_ERROR`
```bash
curl -X POST http://127.0.0.1:8901/api/resolve/command -H "Content-Type: application/json" -d "{\"command\": \"mark chapters as blue markers\", \"context\": {\"chapters\": [{\"title\": \"Intro\", \"start\": 0}], \"fps\": 24}, \"mode\": \"dry-run\"}"
```

---

## Analytics

### GET /api/analytics_inbox
Return unread FEEDBACK messages from analytics bus.
**Response:** `{"messages": [...], "count": 2}`
```bash
curl http://127.0.0.1:8901/api/analytics_inbox
```

### POST /api/analytics/mark
Mark an analytics message as read or actioned.
**Request:** `{"message_id": "msg-123", "new_status": "read"}`
**Response:** `{"success": true, ...}`
**Errors:** `400` (invalid message_id or status)
```bash
curl -X POST http://127.0.0.1:8901/api/analytics/mark -H "Content-Type: application/json" -d "{\"message_id\": \"msg-123\", \"new_status\": \"read\"}"
```

---

## Shorts Pipeline

### POST /api/shorts/assemble
Assemble a short-form video from landscape source.
**Request:** `{"video_path": "C:/AT01/input/video.mov", "target_aspect": "9:16", "max_duration": 60.0, "caption_style": "highlight_word", "enable_face_zoom": true, "enable_emphasis_zoom": true}`
**Response:** `{"output_path": "...", "duration": 58.5, ...}`
**Errors:** `400 FILE_NOT_FOUND` | `500 TOOL_ERROR`
```bash
curl -X POST http://127.0.0.1:8901/api/shorts/assemble -H "Content-Type: application/json" -d "{\"video_path\": \"C:/AT01/input/video.mov\"}"
```

### POST /api/shorts/batch
Batch process videos into shorts.
**Request:** `{"input_dir": "C:/AT01/input", "target_aspect": "9:16", "max_duration": 60.0}`
**Response:** `{"results": [...], "count": 3}`
**Errors:** `400 FILE_NOT_FOUND` | `500 TOOL_ERROR`
```bash
curl -X POST http://127.0.0.1:8901/api/shorts/batch -H "Content-Type: application/json" -d "{\"input_dir\": \"C:/AT01/input\"}"
```

### POST /api/shorts/track
Run person tracking on a video.
**Request:** `{"video_path": "C:/AT01/input/video.mov"}`
**Response:** `{"frames": [...], "persons": [...], ...}`
**Errors:** `400 FILE_NOT_FOUND` | `500 TOOL_ERROR`
```bash
curl -X POST http://127.0.0.1:8901/api/shorts/track -H "Content-Type: application/json" -d "{\"video_path\": \"C:/AT01/input/video.mov\"}"
```

### POST /api/shorts/crop-preview
Generate crop keyframes without rendering.
**Request:** `{"video_path": "C:/AT01/input/video.mov", "target_aspect": "9:16"}`
**Response:** `{"keyframes": [...], ...}`
**Errors:** `400 FILE_NOT_FOUND` | `500 TOOL_ERROR`
```bash
curl -X POST http://127.0.0.1:8901/api/shorts/crop-preview -H "Content-Type: application/json" -d "{\"video_path\": \"C:/AT01/input/video.mov\"}"
```

### POST /api/shorts/captions
Generate animated captions from transcript.
**Request:** `{"video_path": "C:/AT01/input/video.mov", "transcript_path": null, "style": "highlight_word"}`
**Response:** `{"captions": [...], "style": "highlight_word", ...}`
**Errors:** `400 NO_TRANSCRIPT` | `500 TOOL_ERROR`
```bash
curl -X POST http://127.0.0.1:8901/api/shorts/captions -H "Content-Type: application/json" -d "{\"video_path\": \"C:/AT01/input/video.mov\"}"
```

---

## Manifest Bridge (AT → JP Viewer)

### POST /api/manifest/sync
Scan a video directory and generate both raptor-library.json + assembly_manifest.json.
**Request:** `{"video_dir": "C:/AT01/input", "output_dir": "output", "chunks_dir": null}`
**Response:** `{"raptor_library_path": "output/raptor-library.json", "assembly_manifest_path": "output/assembly_manifest.json", "entry_count": 5, "clip_count": 12, "errors": []}`
**Errors:** `500 SYNC_ERROR`
```bash
curl -X POST http://127.0.0.1:8901/api/manifest/sync -H "Content-Type: application/json" -d "{\"video_dir\": \"C:/AT01/input\", \"output_dir\": \"output\"}"
```

### POST /api/manifest/raptor-library
Generate a raptor-library.json entry for a single video (using cached pipeline data).
**Request:** `{"video_path": "C:/AT01/input/video.mov", "output_path": "output/raptor-library.json", "source_root": null}`
**Response:** `{"generated": "...", "source_root": "...", "total_files": 1, "entries": [...]}`
**Errors:** `400 FILE_NOT_FOUND` | `500 MANIFEST_ERROR`
```bash
curl -X POST http://127.0.0.1:8901/api/manifest/raptor-library -H "Content-Type: application/json" -d "{\"video_path\": \"C:/AT01/input/video.mov\"}"
```

### POST /api/manifest/assembly
Generate an assembly_manifest.json from cached transcription chunks.
**Request:** `{"source_id": null, "platform": "tiktok", "aspect": "9:16", "output_path": "output/assembly_manifest.json"}`
**Response:** `{"generated": "...", "source_clip": "video.mov", "clips": [...]}`
**Errors:** `400 NO_DATA` | `500 MANIFEST_ERROR`
```bash
curl -X POST http://127.0.0.1:8901/api/manifest/assembly -H "Content-Type: application/json" -d "{\"platform\": \"tiktok\", \"aspect\": \"9:16\"}"
```

---

## Utility

### POST /api/benchmark
Run timed benchmarks on pipeline stages.
**Request:** `{"video_path": "C:/AT01/input/video.mov", "runs": 3}`
**Response:** `{"transcribe": {"mean_s": 12.5, "target_s": 30, "pass": true}, "search": {"mean_s": 0.02, "target_s": 0.1, "pass": true}, ...}`
**Errors:** `400 FILE_NOT_FOUND` | `500 PROCESSING_ERROR`
```bash
curl -X POST http://127.0.0.1:8901/api/benchmark -H "Content-Type: application/json" -d "{\"video_path\": \"C:/AT01/input/IMG_5769.MOV\", \"runs\": 1}"
```

---

## WebSocket

### WS /ws/progress
Real-time pipeline progress and new output notifications.
**Messages received:**
- Progress: `{"type": "progress", "stage": "transcribe", "status": "running", "detail": "..."}`
- New output: `{"type": "new_output", "file": {"filename": "...", "path": "...", "size_mb": 12.5}}`
```javascript
const ws = new WebSocket("ws://127.0.0.1:8901/ws/progress");
ws.onmessage = (e) => console.log(JSON.parse(e.data));
```

---

## Static / Viewer

### GET /
Serve the clip viewer HTML (v2, falls back to v1).
```bash
curl http://127.0.0.1:8901/
```

### GET /v1
Serve the original clip viewer v1.
```bash
curl http://127.0.0.1:8901/v1
```

### GET /video/{path}
Serve video files with byte-range support for browser scrubbing.
Only serves from allowed directories (`C:\AT01\input`, `C:\AT01\output`, `C:\AT01\temp`).
**Headers:** Supports `Range: bytes=0-1023` for partial content (HTTP 206).
**Errors:** `403` (path traversal or disallowed directory) | `404` (file not found)
```bash
curl http://127.0.0.1:8901/video/C:/AT01/input/IMG_5769.MOV -H "Range: bytes=0-1023"
```

---

## Error Response Format

All error responses follow a standardized schema:
```json
{
  "detail": {
    "status": "error",
    "error": "Human-readable message",
    "code": "ERROR_CODE",
    "endpoint": "/api/..."
  }
}
```

Error codes:
| Code | HTTP Status | Description |
|------|-------------|-------------|
| `FILE_NOT_FOUND` | 400 | Video/file path does not exist |
| `INVALID_INPUT` | 400 | Missing or invalid required field |
| `NO_TRANSCRIPT` | 400/404 | No transcription data available |
| `NO_SESSION` | 400/404 | No active session data |
| `NO_SPEAKERS` | 400 | No speaker map available |
| `NO_INDEX` | 404 | No transcript index available |
| `NO_MANIFEST` | 400 | No batch manifest available |
| `NOT_FOUND` | 404 | Resource not found |
| `TOOL_ERROR` | 500 | Internal tool processing failed |
| `RESOLVE_OFFLINE` | 503 | Resolve endpoint called but not running |
| `PROCESSING_ERROR` | 500 | Unhandled internal error |

---

## Benchmark Results (2026-02-27)

Machine: ENKI64 | RTX A6000 48GB | 128GB RAM | Python 3.12.10 | Resolve Studio 20.3.1.6 running

### test_with_silence.mov (60s, 2 silence gaps)

| Stage | Time | Target | Status |
|-------|------|--------|--------|
| Transcribe (CUDA float16) | 7.09s | <30s | PASS |
| Silence detect | 1.34s | <10s | PASS |
| Chapter detect | <0.001s | <5s | PASS |
| Search | <0.001s | <0.1s | PASS |
| **Full pipeline** | **8.44s** | <60s | **PASS** |

### IMG_5769.MOV (424.81s / 7 min, continuous speech)

| Stage | Time | Target | Status |
|-------|------|--------|--------|
| Transcribe (CUDA int8) | 62.05s | <30s | FAIL |
| Silence detect | 9.39s | <10s | PASS |
| Chapter detect | <0.001s | <5s | PASS |
| Search | <0.001s | <0.1s | PASS |
| **Full pipeline** | **71.44s** | <60s | **FAIL** |

### Known issues
- CUDA float16 (large-v3) crashes on long audio (>60s) when Resolve holds GPU resources
- Workaround: use int8 compute type or close Resolve before transcription
- CPU fallback: 580s for 7min audio (10x realtime)
- Transcription is the bottleneck — all other stages complete in <10s total

### Resolve live tests
18/18 passed including 4 render tests (125s total)

---

## Video Archive Scanner

### POST /api/scan/local
Scan a local directory for video files and add to catalog.
**Request:** `{"directory": "C:/Videos", "recursive": true}`
**Response:** `{"added": 3, "skipped": 0, "total": 3, "catalog_path": "temp/video_catalog.json"}`
**Errors:** `400 DIR_NOT_FOUND` | `400 INVALID_INPUT` | `500 PROCESSING_ERROR`
```bash
curl -X POST http://127.0.0.1:8901/api/scan/local -H "Content-Type: application/json" -d "{\"directory\": \"C:/Videos\"}"
```

### POST /api/scan/drive
Scan Google Drive for video files and add to catalog. Requires OAuth2 credentials.
**Request:** `{"folder_id": "abc123", "credentials_path": "temp/gdrive_credentials.json", "token_path": "temp/gdrive_token.json", "max_results": 100}`
**Response:** `{"added": 5, "skipped": 0, "total": 5, "catalog_path": "temp/video_catalog.json"}`
**Errors:** `401 AUTH_ERROR` | `500 API_ERROR` | `500 PROCESSING_ERROR`
```bash
curl -X POST http://127.0.0.1:8901/api/scan/drive -H "Content-Type: application/json" -d "{\"folder_id\": \"abc123\"}"
```

### POST /api/scan/dropbox
Scan Dropbox for video files and add to catalog. Requires access token.
**Request:** `{"folder_path": "/Videos", "access_token": "...", "recursive": true, "max_results": 100}`
**Response:** `{"added": 2, "skipped": 0, "total": 2, "catalog_path": "temp/video_catalog.json"}`
**Errors:** `401 AUTH_ERROR` | `500 API_ERROR` | `500 PROCESSING_ERROR`
```bash
curl -X POST http://127.0.0.1:8901/api/scan/dropbox -H "Content-Type: application/json" -d "{\"folder_path\": \"/Videos\"}"
```

### POST /api/probe
Probe a video file for metadata (duration, codec, resolution, fps, etc.).
**Request:** `{"video_path": "C:/Videos/clip.mp4"}`
**Response:** `{"filename": "clip.mp4", "duration_sec": 60.0, "width": 1920, "height": 1080, "fps": 24.0, "video_codec": "h264", "audio_codec": "aac", "bitrate_kbps": 5000, "audio_channels": 2, "file_size_mb": 50.0, "format_name": "mp4"}`
**Errors:** `400 FILE_NOT_FOUND` | `500 PROBE_ERROR` | `500 PROCESSING_ERROR`
```bash
curl -X POST http://127.0.0.1:8901/api/probe -H "Content-Type: application/json" -d "{\"video_path\": \"C:/Videos/clip.mp4\"}"
```

### POST /api/scan/frames
Run scene detection (PySceneDetect) + CLIP frame labeling on a video. All local GPU, zero cloud tokens.
**Request:** `{"video_path": "C:/Videos/clip.mp4", "labels": ["person talking", "b-roll"], "scene_threshold": 27.0, "top_k": 3}`
**Response:** `{"video_path": "clip.mp4", "scenes": [{"start_sec": 0.0, "end_sec": 5.0, "duration_sec": 5.0, "frame_labels": [{"label": "person talking", "score": 0.92}]}], "frames": [...], "scene_count": 3}`
**Errors:** `400 FILE_NOT_FOUND` | `500 SCENE_ERROR` | `500 PROCESSING_ERROR`
```bash
curl -X POST http://127.0.0.1:8901/api/scan/frames -H "Content-Type: application/json" -d "{\"video_path\": \"C:/Videos/clip.mp4\"}"
```

### GET /api/catalog
Return the full video catalog.
**Response:** `{"version": 1, "created": "...", "updated": "...", "entries": {"path/to/video.mp4": {...}, ...}}`
```bash
curl http://127.0.0.1:8901/api/catalog
```

### POST /api/catalog/search
Search the video catalog by filename or CLIP frame label.
**Request:** `{"query": "interview"}`
**Response:** `{"query": "interview", "results": [{"key": "...", "match_type": "filename", "filename": "interview.mp4", ...}], "count": 1}`
**Errors:** `400 INVALID_INPUT` (empty query)
```bash
curl -X POST http://127.0.0.1:8901/api/catalog/search -H "Content-Type: application/json" -d "{\"query\": \"interview\"}"
```

### GET /api/library
Return the current library JSON (demo or real footage). Controlled by `LIBRARY_PATH` env var (default: `demo-library.json`).
**Response:** `{"entries": [...], "count": 4, "demo_mode": true}`
```bash
curl http://127.0.0.1:8901/api/library
```

### GET /api/library/chapters
Return chapter boundaries for all library entries, computed from transcript gap analysis (20s silence = chapter break).
**Response:** `{"files": [{"filename": "...", "duration": 432.0, "chapters": [{"chapter_id": 1, "start": 0.0, "end": 63.0, "duration": 63.0, "title": "...", "segment_count": 7}]}], "total_chapters": 20}`
```bash
curl http://127.0.0.1:8901/api/library/chapters
```

### GET /api/library/search
Search library entries by keyword across transcript text and filenames.
**Query params:** `q` (search term, case-insensitive)
**Response:** `{"results": [{"filename": "...", "duration": 295.0, "match_count": 3, "matches": [{"field": "transcript", "start": 50.0, "end": 55.0, "text": "..."}]}], "query": "Scrooge", "count": 2}`
```bash
curl "http://127.0.0.1:8901/api/library/search?q=Scrooge"
```
