"""EdBot FastAPI server — wraps pipeline tools and serves clip viewer UI.

Endpoints:
    GET  /health              -> health alias (same as /api/health)
    GET  /api/health          -> tool status
    POST /api/transcribe      -> run transcription
    POST /api/silence         -> run silence detection
    POST /api/parse           -> run NLP action parser
    POST /api/execute         -> run executor
    GET  /api/chunks          -> cached chunks.json
    GET  /api/silence_map     -> cached silence_map.json
    GET  /api/outputs         -> output manifest (watcher-backed)
    GET  /api/chapters        -> run chapter detection
    GET  /api/speakers        -> run speaker detection
    POST /api/portrait_crop   -> crop video to portrait
    POST /api/tiktok          -> generate TikTok chunks
    GET  /api/session         -> current session state
    GET  /api/clips_manifest  -> cached clips manifest
    GET  /api/gpu_status      -> CUDA availability check
    GET  /api/analytics_inbox -> unread analytics feedback
    WS   /ws/progress         -> real-time progress + new_output events
    GET  /                    -> serve viewer HTML
    GET  /video/{path}        -> serve video files with byte-range support
"""

import asyncio
import logging
import mimetypes
import os
import re
import sys
from pathlib import Path
from typing import Any

import uvicorn
from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, Response, StreamingResponse
from pydantic import BaseModel

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Tool imports — tools live in agents/edbot/tools/
# ---------------------------------------------------------------------------
_tools_dir = str(Path(__file__).resolve().parent / "tools")
if _tools_dir not in sys.path:
    sys.path.insert(0, _tools_dir)

from transcribe import transcribe_video
from silence_detect import detect_silence
from nlp_action import parse_command
from executor import execute_action
from chapter_detect import detect_chapters
from speaker_detect import detect_speakers
from portrait_crop import portrait_crop
from tiktok_chunk import generate_tiktok_chunks
from analytics_reader import read_messages
from output_watcher import OutputWatcher

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

TOOL_NAMES = ["transcribe", "silence_detect", "nlp_action", "executor",
              "chapter_detect", "speaker_detect", "portrait_crop", "tiktok_chunk",
              "analytics_reader"]

MEDIA_EXTENSIONS = {".mp4", ".mov", ".mkv", ".avi", ".webm"}

ALLOWED_VIDEO_DIRS = [
    Path(r"C:\AT01\input").resolve(),
    Path(r"C:\AT01\output").resolve(),
    Path(r"C:\AT01\temp").resolve(),
    Path(r"C:\NB10\media_test\in").resolve(),
]

STATIC_DIR = Path(__file__).resolve().parent / "static"
OUTPUT_DIR = Path(r"C:\AT01\output")

# ---------------------------------------------------------------------------
# In-memory cache
# ---------------------------------------------------------------------------

_cache: dict[str, Any] = {
    "chunks": None,
    "silence_map": None,
    "last_input": None,
}

_session: dict[str, Any] = {
    "video_path": None,
    "chunks": None,
    "silence_map": None,
    "chapters": None,
    "speaker_map": None,
    "clips_manifest": None,
}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def error_response(status_code: int, error_msg: str, error_code: str):
    """Raise HTTPException with a consistent JSON error body."""
    raise HTTPException(
        status_code=status_code,
        detail={"status": "error", "error": error_msg, "code": error_code},
    )


def safe_gpu_call(func, *args, **kwargs):
    """Run a GPU-capable function, falling back gracefully on CUDA errors."""
    try:
        return func(*args, **kwargs)
    except Exception as exc:
        error_str = str(exc).lower()
        if any(term in error_str for term in ("cuda", "gpu", "cublas", "cudnn", "nccl",
                                               "exit 127", "out of memory", "oom")):
            return {"error": f"GPU failed: {exc}", "method": "gpu_failed", "fallback": True}
        raise

# ---------------------------------------------------------------------------
# WebSocket connection manager
# ---------------------------------------------------------------------------

class ConnectionManager:
    """Manages WebSocket connections for real-time event broadcasting."""

    def __init__(self):
        self.active: list[WebSocket] = []

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        self.active.append(ws)

    def disconnect(self, ws: WebSocket) -> None:
        if ws in self.active:
            self.active.remove(ws)

    async def broadcast(self, message: dict) -> None:
        for ws in list(self.active):
            try:
                await ws.send_json(message)
            except Exception:
                self.disconnect(ws)


manager = ConnectionManager()


# ---------------------------------------------------------------------------
# OutputWatcher integration
# ---------------------------------------------------------------------------

def _on_new_output(file_info: dict) -> None:
    """Callback from OutputWatcher — broadcast new_output to WebSocket clients."""
    try:
        loop = asyncio.get_running_loop()
        loop.create_task(manager.broadcast({
            "type": "new_output",
            "file": file_info,
        }))
    except RuntimeError:
        # No event loop running (e.g. during tests). Skip broadcast.
        pass


_watcher: OutputWatcher | None = None


def get_watcher() -> OutputWatcher:
    """Get or create the singleton OutputWatcher."""
    global _watcher
    if _watcher is None:
        _watcher = OutputWatcher(
            watch_dir=str(OUTPUT_DIR),
            manifest_path=str(OUTPUT_DIR / "manifest.json"),
            on_new_file=_on_new_output,
        )
    return _watcher


async def broadcast_progress(stage: str, status: str, detail: str = "") -> None:
    """Broadcast a pipeline progress event to all WebSocket clients."""
    await manager.broadcast({
        "type": "progress",
        "stage": stage,
        "status": status,
        "detail": detail,
    })


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class ProcessRequest(BaseModel):
    input_path: str
    output_dir: str = "output"


class ParseRequest(BaseModel):
    text: str
    input_path: str = ""


class ExecuteRequest(BaseModel):
    action: dict
    input_path: str | None = None


class CropRequest(BaseModel):
    input_path: str | None = None
    output_dir: str = "output"
    method: str = "center"
    start: float | None = None
    end: float | None = None


class TikTokRequest(BaseModel):
    input_path: str | None = None
    output_dir: str = "output"
    max_duration: float = 60.0
    crop_method: str = "center"


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

app = FastAPI(title="EdBot Pipeline Server", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# API endpoints
# ---------------------------------------------------------------------------

@app.get("/api/health")
async def health():
    """Return server status and available tool list."""
    return {"status": "ok", "tools": TOOL_NAMES}


@app.get("/health")
async def health_alias():
    """Alias for /api/health — return server status and available tool list."""
    return {"status": "ok", "tools": TOOL_NAMES}


@app.post("/api/transcribe")
def api_transcribe(req: ProcessRequest):
    """Run transcribe_video and return chunks data."""
    # Input validation
    p = Path(req.input_path)
    if not p.exists():
        error_response(400, f"file not found: {req.input_path}", "FILE_NOT_FOUND")
    if p.suffix.lower() not in MEDIA_EXTENSIONS:
        error_response(400, f"unsupported file extension: {p.suffix}", "INVALID_INPUT")
    result = transcribe_video(req.input_path, req.output_dir)
    if result.get("error"):
        error_response(500, result["error"], "TOOL_ERROR")
    _cache["chunks"] = result
    _cache["last_input"] = req.input_path
    _session["video_path"] = req.input_path
    _session["chunks"] = result.get("chunks")
    return result


@app.post("/api/silence")
def api_silence(req: ProcessRequest):
    """Run silence detection and return silence map."""
    result = detect_silence(req.input_path, output_dir=req.output_dir)
    if result.get("error"):
        error_response(500, result["error"], "TOOL_ERROR")
    _cache["silence_map"] = result
    _cache["last_input"] = req.input_path
    _session["silence_map"] = result
    return result


@app.post("/api/parse")
def api_parse(req: ParseRequest):
    """Run NLP action parser and return action JSON."""
    result = parse_command(req.text, req.input_path or None)
    return result


@app.post("/api/execute")
def api_execute(req: ExecuteRequest):
    """Run executor on an action dict and return result."""
    result = execute_action(req.action, req.input_path)
    if result.get("status") == "error":
        error_response(500, result.get("error", "execution failed"), "TOOL_ERROR")
    return result


@app.get("/api/chunks")
async def api_chunks():
    """Return last cached chunks result."""
    if _cache["chunks"] is None:
        error_response(404, "no chunks cached — run /api/transcribe first", "NO_TRANSCRIPT")
    return _cache["chunks"]


@app.get("/api/silence_map")
async def api_silence_map():
    """Return last cached silence map."""
    if _cache["silence_map"] is None:
        error_response(404, "no silence map cached — run /api/silence first", "NO_SESSION")
    return _cache["silence_map"]


@app.get("/api/outputs")
async def api_outputs():
    """Return output manifest from OutputWatcher (falls back to dir listing)."""
    watcher = get_watcher()
    manifest = watcher.get_manifest()
    if manifest.get("files"):
        return manifest
    # Fallback: direct dir listing if manifest is empty
    if not OUTPUT_DIR.exists():
        return {"watch_dir": str(OUTPUT_DIR), "files": [], "last_updated": None}
    files = []
    for f in OUTPUT_DIR.iterdir():
        if f.is_file():
            files.append({
                "filename": f.name,
                "path": str(f),
                "size_mb": round(f.stat().st_size / (1024 * 1024), 2),
            })
    return {"watch_dir": str(OUTPUT_DIR), "files": files, "last_updated": None}


# ---------------------------------------------------------------------------
# Round 3 endpoints
# ---------------------------------------------------------------------------

@app.get("/api/chapters")
def api_chapters():
    """Run chapter detection on cached chunks + silence_map."""
    chunks = _session.get("chunks") or (_cache.get("chunks") or {}).get("chunks")
    if not chunks:
        error_response(400, "no chunks — run /api/transcribe first", "NO_TRANSCRIPT")
    silence_map = _session.get("silence_map") or _cache.get("silence_map")
    chapters = detect_chapters(chunks, silence_map=silence_map)
    _session["chapters"] = chapters
    return {"chapters": chapters}


@app.get("/api/speakers")
def api_speakers():
    """Run speaker detection on session video."""
    video_path = _session.get("video_path") or _cache.get("last_input")
    if not video_path:
        error_response(400, "no video path — load a video first", "NO_SESSION")
    chunks = _session.get("chunks") or (_cache.get("chunks") or {}).get("chunks")
    result = detect_speakers(video_path, chunks=chunks)
    if result.get("error"):
        error_response(500, result["error"], "TOOL_ERROR")
    _session["speaker_map"] = result
    return result


class LabelRequest(BaseModel):
    labels: dict[str, str]  # {"SPEAKER_0": "Ari", "SPEAKER_1": "Alex"}


@app.post("/api/label_speakers")
def api_label_speakers(req: LabelRequest):
    """Update speaker labels in session speaker_map."""
    # Validate label keys match SPEAKER_\d+ and values are non-empty strings
    for key, value in req.labels.items():
        if not re.fullmatch(r"SPEAKER_\d+", key):
            error_response(400, f"invalid speaker key: {key} (expected SPEAKER_N)", "INVALID_INPUT")
        if not isinstance(value, str) or not value.strip():
            error_response(400, f"speaker label for {key} must be a non-empty string", "INVALID_INPUT")
    speaker_map = _session.get("speaker_map")
    if speaker_map is None:
        error_response(400, "no speaker map — run /api/speakers first", "NO_SPEAKERS")
    # Replace labels in segments and chunk_speakers
    for seg in speaker_map.get("segments", []):
        if seg.get("speaker") in req.labels:
            seg["speaker"] = req.labels[seg["speaker"]]
    for chunk_id, spk in list(speaker_map.get("chunk_speakers", {}).items()):
        if spk in req.labels:
            speaker_map["chunk_speakers"][chunk_id] = req.labels[spk]
    # Update speakers list
    speaker_map["speakers"] = [req.labels.get(s, s) for s in speaker_map.get("speakers", [])]
    _session["speaker_map"] = speaker_map
    return speaker_map


@app.post("/api/portrait_crop")
def api_portrait_crop(req: CropRequest):
    """Crop a video to portrait orientation."""
    if req.method not in ("center", "face"):
        error_response(400, f"invalid crop method: {req.method} (expected 'center' or 'face')", "INVALID_INPUT")
    input_path = req.input_path or _session.get("video_path") or _cache.get("last_input")
    if not input_path:
        error_response(400, "no input path", "NO_SESSION")
    result = portrait_crop(input_path, req.output_dir, method=req.method, start=req.start, end=req.end)
    if result.get("status") == "error":
        error_response(500, result.get("error", "crop failed"), "TOOL_ERROR")
    return result


@app.post("/api/tiktok")
def api_tiktok(req: TikTokRequest):
    """Generate TikTok chunks from video."""
    if req.max_duration <= 0 or req.max_duration > 300:
        error_response(400, f"max_duration must be > 0 and <= 300, got {req.max_duration}", "INVALID_INPUT")
    if req.crop_method not in ("center", "face"):
        error_response(400, f"invalid crop_method: {req.crop_method} (expected 'center' or 'face')", "INVALID_INPUT")
    input_path = req.input_path or _session.get("video_path") or _cache.get("last_input")
    if not input_path:
        error_response(400, "no input path", "NO_SESSION")
    chapters = _session.get("chapters")
    if not chapters:
        # Auto-detect chapters first
        chunks = _session.get("chunks") or (_cache.get("chunks") or {}).get("chunks")
        if not chunks:
            error_response(400, "no chunks — run /api/transcribe first", "NO_TRANSCRIPT")
        silence_map = _session.get("silence_map") or _cache.get("silence_map")
        chapters = detect_chapters(chunks, silence_map=silence_map)
        _session["chapters"] = chapters
    chunks = _session.get("chunks") or (_cache.get("chunks") or {}).get("chunks")
    result = generate_tiktok_chunks(input_path, chapters, chunks=chunks,
                                     output_dir=req.output_dir,
                                     max_duration=req.max_duration,
                                     crop_method=req.crop_method)
    _session["clips_manifest"] = result
    return result


# ---------------------------------------------------------------------------
# Shorts pipeline endpoints
# ---------------------------------------------------------------------------

class ShortsAssembleRequest(BaseModel):
    video_path: str
    target_aspect: str = "9:16"
    max_duration: float = 60.0
    caption_style: str = "highlight_word"
    enable_face_zoom: bool = True
    enable_emphasis_zoom: bool = True


class ShortsBatchRequest(BaseModel):
    input_dir: str
    target_aspect: str = "9:16"
    max_duration: float = 60.0


class ShortsTrackRequest(BaseModel):
    video_path: str


class ShortsCropPreviewRequest(BaseModel):
    video_path: str
    target_aspect: str = "9:16"


class ShortsCaptionsRequest(BaseModel):
    video_path: str | None = None
    transcript_path: str | None = None
    style: str = "highlight_word"


@app.post("/api/shorts/assemble")
def api_shorts_assemble(req: ShortsAssembleRequest):
    """Assemble a short-form video from landscape source."""
    p = Path(req.video_path)
    if not p.exists():
        error_response(400, f"file not found: {req.video_path}", "FILE_NOT_FOUND")
    try:
        from shorts.shorts_assembler import assemble_short
        result = assemble_short(
            req.video_path,
            target_aspect=req.target_aspect,
            max_duration=req.max_duration,
            caption_style=req.caption_style,
            enable_face_zoom=req.enable_face_zoom,
            enable_emphasis_zoom=req.enable_emphasis_zoom,
        )
        return result
    except Exception as exc:
        error_response(500, str(exc), "TOOL_ERROR")


@app.post("/api/shorts/batch")
def api_shorts_batch(req: ShortsBatchRequest):
    """Batch process videos into shorts."""
    p = Path(req.input_dir)
    if not p.exists():
        error_response(400, f"directory not found: {req.input_dir}", "FILE_NOT_FOUND")
    try:
        from shorts.shorts_assembler import batch_assemble_shorts
        result = batch_assemble_shorts(
            req.input_dir,
            target_aspect=req.target_aspect,
            max_duration=req.max_duration,
        )
        return result
    except Exception as exc:
        error_response(500, str(exc), "TOOL_ERROR")


@app.post("/api/shorts/track")
def api_shorts_track(req: ShortsTrackRequest):
    """Run person tracking on a video (for debug/preview)."""
    p = Path(req.video_path)
    if not p.exists():
        error_response(400, f"file not found: {req.video_path}", "FILE_NOT_FOUND")
    try:
        from shorts.person_tracker import track_persons
        result = track_persons(req.video_path)
        return result
    except Exception as exc:
        error_response(500, str(exc), "TOOL_ERROR")


@app.post("/api/shorts/crop-preview")
def api_shorts_crop_preview(req: ShortsCropPreviewRequest):
    """Generate crop keyframes without rendering (for UI visualization)."""
    p = Path(req.video_path)
    if not p.exists():
        error_response(400, f"file not found: {req.video_path}", "FILE_NOT_FOUND")
    try:
        from shorts.person_tracker import track_persons
        from shorts.smart_crop import generate_crop_keyframes
        tracking = track_persons(req.video_path)
        crop_kf = generate_crop_keyframes(tracking, target_aspect=req.target_aspect)
        return crop_kf
    except Exception as exc:
        error_response(500, str(exc), "TOOL_ERROR")


@app.post("/api/shorts/captions")
def api_shorts_captions(req: ShortsCaptionsRequest):
    """Generate animated captions from transcript."""
    transcript_path = req.transcript_path
    if not transcript_path and req.video_path:
        # Try to find transcript from video stem
        vp = Path(req.video_path)
        candidates = [
            Path("temp") / f"{vp.stem}_transcript.json",
            Path("output") / "transcript.json",
        ]
        for c in candidates:
            if c.exists():
                transcript_path = str(c)
                break
    if not transcript_path or not Path(transcript_path).exists():
        error_response(400, "no transcript found — provide transcript_path or run transcribe first", "NO_TRANSCRIPT")
    try:
        from shorts.animated_captions import generate_animated_captions
        result = generate_animated_captions(
            transcript_path, style=req.style,
        )
        return result
    except Exception as exc:
        error_response(500, str(exc), "TOOL_ERROR")


# ---------------------------------------------------------------------------
# Round 6: transcript intelligence endpoints
# ---------------------------------------------------------------------------

class BatchTranscribeRequest(BaseModel):
    input_dir: str


class AutoNameRequest(BaseModel):
    manifest_path: str = "temp/batch_manifest.json"


class AutoChapterRequest(BaseModel):
    video_path: str


class SearchTranscriptsRequest(BaseModel):
    query: str
    max_results: int = 20


class MatchShotsRequest(BaseModel):
    similarity: float = 0.6


@app.post("/api/batch-transcribe")
def api_batch_transcribe(req: BatchTranscribeRequest):
    """Batch transcribe all videos in a directory."""
    p = Path(req.input_dir)
    if not p.exists():
        error_response(400, f"directory not found: {req.input_dir}", "FILE_NOT_FOUND")
    try:
        from batch_transcribe import batch_transcribe
        result = batch_transcribe(req.input_dir)
        return result
    except Exception as exc:
        error_response(500, str(exc), "TOOL_ERROR")


@app.post("/api/auto-name")
def api_auto_name(req: AutoNameRequest):
    """Auto-name files from batch manifest."""
    manifest_path = Path(req.manifest_path)
    if not manifest_path.exists():
        error_response(400, f"manifest not found: {req.manifest_path}", "FILE_NOT_FOUND")
    try:
        import json
        from auto_name import batch_auto_name
        with open(manifest_path, "r", encoding="utf-8") as f:
            manifest = json.load(f)
        result = batch_auto_name(manifest, str(manifest_path.parent))
        return result
    except Exception as exc:
        error_response(500, str(exc), "TOOL_ERROR")


@app.post("/api/auto-chapter")
def api_auto_chapter(req: AutoChapterRequest):
    """Generate enhanced chapters with NLP titles."""
    p = Path(req.video_path)
    if not p.exists():
        error_response(400, f"file not found: {req.video_path}", "FILE_NOT_FOUND")
    try:
        from auto_chapter import auto_chapter
        result = auto_chapter(req.video_path)
        return result
    except Exception as exc:
        error_response(500, str(exc), "TOOL_ERROR")


@app.get("/api/transcript-index")
def api_transcript_index():
    """Return transcript index if exists."""
    import json
    index_path = Path("temp") / "transcript_index.json"
    if not index_path.exists():
        error_response(404, "no transcript index — run batch transcribe first", "NO_INDEX")
    with open(index_path, "r", encoding="utf-8") as f:
        return json.load(f)


@app.post("/api/search-transcripts")
def api_search_transcripts(req: SearchTranscriptsRequest):
    """Search transcript index for query."""
    try:
        import json
        from transcript_index import search_index
        index_path = Path("temp") / "transcript_index.json"
        if not index_path.exists():
            error_response(404, "no transcript index", "NO_INDEX")
        with open(index_path, "r", encoding="utf-8") as f:
            index = json.load(f)
        results = search_index(index, req.query, req.max_results)
        return {"query": req.query, "results": results, "count": len(results)}
    except Exception as exc:
        error_response(500, str(exc), "TOOL_ERROR")


@app.post("/api/match-shots")
def api_match_shots(req: MatchShotsRequest):
    """Find matching shots across transcribed videos."""
    try:
        import json
        from shot_matcher import find_matching_shots
        manifest_path = Path("temp") / "batch_manifest.json"
        if not manifest_path.exists():
            error_response(400, "no batch manifest — run batch transcribe first", "NO_MANIFEST")
        with open(manifest_path, "r", encoding="utf-8") as f:
            manifest = json.load(f)
        results = find_matching_shots(manifest, "temp", req.similarity)
        return {"matches": results, "count": len(results)}
    except Exception as exc:
        error_response(500, str(exc), "TOOL_ERROR")


@app.get("/api/analytics_inbox")
async def api_analytics_inbox():
    """Return unread FEEDBACK messages from anabot-to-edbot bus."""
    messages = read_messages(filter_type="FEEDBACK", unread_only=True)
    return {"messages": messages, "count": len(messages)}


# ---------------------------------------------------------------------------
# WebSocket endpoint
# ---------------------------------------------------------------------------

@app.websocket("/ws/progress")
async def ws_progress(ws: WebSocket):
    """Real-time events: new_output notifications + pipeline progress."""
    await manager.connect(ws)
    try:
        while True:
            await ws.receive_text()  # keepalive
    except WebSocketDisconnect:
        manager.disconnect(ws)


@app.get("/api/session")
async def api_session():
    """Return current session state."""
    return {
        "video_path": _session.get("video_path"),
        "has_chunks": _session.get("chunks") is not None or _cache.get("chunks") is not None,
        "has_silence_map": _session.get("silence_map") is not None or _cache.get("silence_map") is not None,
        "has_chapters": _session.get("chapters") is not None,
        "has_speaker_map": _session.get("speaker_map") is not None,
        "has_clips_manifest": _session.get("clips_manifest") is not None,
    }


@app.get("/api/clips_manifest")
async def api_clips_manifest():
    """Return cached clips manifest."""
    manifest = _session.get("clips_manifest")
    if manifest is None:
        error_response(400, "no clips manifest — run /api/tiktok first", "NO_SESSION")
    return manifest


@app.get("/api/gpu_status")
async def api_gpu_status():
    """Check CUDA availability."""
    try:
        import torch
        cuda_available = torch.cuda.is_available()
        device_name = torch.cuda.get_device_name(0) if cuda_available else None
        return {"cuda_available": cuda_available, "device": device_name}
    except ImportError:
        return {"cuda_available": False, "device": None, "error": "torch not installed"}


# ---------------------------------------------------------------------------
# Video serving with byte-range support
# ---------------------------------------------------------------------------

def _is_path_allowed(file_path: Path) -> bool:
    """Check that resolved path is inside one of the allowed directories."""
    try:
        resolved = file_path.resolve()
    except (OSError, ValueError):
        return False
    for allowed in ALLOWED_VIDEO_DIRS:
        try:
            resolved.relative_to(allowed)
            return True
        except ValueError:
            continue
    return False


@app.get("/video/{path:path}")
async def serve_video(path: str, request: Request):
    """Serve video files with byte-range support for browser scrubbing.

    Only serves from allowed directories. Rejects path traversal attempts.
    """
    # Reject obvious traversal attempts before even building a Path
    if ".." in path:
        raise HTTPException(status_code=403, detail="path traversal not allowed")

    file_path = Path(path)

    # If the path is not absolute, try resolving against allowed dirs
    if not file_path.is_absolute():
        # Try each allowed dir
        found = None
        for allowed_dir in ALLOWED_VIDEO_DIRS:
            candidate = allowed_dir / path
            if candidate.exists() and _is_path_allowed(candidate):
                found = candidate
                break
        if found is None:
            raise HTTPException(status_code=404, detail="file not found")
        file_path = found
    else:
        if not _is_path_allowed(file_path):
            raise HTTPException(status_code=403, detail="path not in allowed directories")

    if not file_path.exists() or not file_path.is_file():
        raise HTTPException(status_code=404, detail="file not found")

    # Determine content type
    content_type, _ = mimetypes.guess_type(str(file_path))
    if content_type is None:
        content_type = "application/octet-stream"

    file_size = file_path.stat().st_size

    # Handle Range header for byte-range requests (video scrubbing)
    range_header = request.headers.get("range")
    if range_header:
        # Parse "bytes=start-end"
        try:
            range_spec = range_header.replace("bytes=", "")
            parts = range_spec.split("-")
            start = int(parts[0]) if parts[0] else 0
            end = int(parts[1]) if parts[1] else file_size - 1
        except (ValueError, IndexError):
            raise HTTPException(status_code=416, detail="invalid range")

        if start >= file_size or end >= file_size or start > end:
            raise HTTPException(
                status_code=416,
                detail="range not satisfiable",
            )

        content_length = end - start + 1

        def iter_file():
            with open(file_path, "rb") as f:
                f.seek(start)
                remaining = content_length
                while remaining > 0:
                    chunk_size = min(8192, remaining)
                    data = f.read(chunk_size)
                    if not data:
                        break
                    remaining -= len(data)
                    yield data

        return StreamingResponse(
            iter_file(),
            status_code=206,
            media_type=content_type,
            headers={
                "Content-Range": f"bytes {start}-{end}/{file_size}",
                "Accept-Ranges": "bytes",
                "Content-Length": str(content_length),
            },
        )

    # Full file response
    return FileResponse(
        path=str(file_path),
        media_type=content_type,
        headers={"Accept-Ranges": "bytes"},
    )


# ---------------------------------------------------------------------------
# Static viewer
# ---------------------------------------------------------------------------

@app.get("/", response_class=HTMLResponse)
async def serve_viewer():
    """Serve the clip viewer v2 HTML page (falls back to v1)."""
    v2_path = STATIC_DIR / "viewer_v2.html"
    v1_path = STATIC_DIR / "viewer.html"
    if v2_path.exists():
        return FileResponse(str(v2_path), media_type="text/html")
    if v1_path.exists():
        return FileResponse(str(v1_path), media_type="text/html")
    return HTMLResponse(
        content="<html><body><h1>EdBot Clip Viewer</h1>"
        "<p>No viewer found. Place viewer.html or viewer_v2.html in agents/edbot/static/</p>"
        "</body></html>",
        status_code=200,
    )


@app.get("/v1", response_class=HTMLResponse)
async def serve_viewer_v1():
    """Serve the original clip viewer HTML page."""
    viewer_path = STATIC_DIR / "viewer.html"
    if not viewer_path.exists():
        raise HTTPException(status_code=404, detail="viewer.html not found")
    return FileResponse(str(viewer_path), media_type="text/html")


# ---------------------------------------------------------------------------
# Lifecycle: start/stop watcher with server
# ---------------------------------------------------------------------------

@app.on_event("startup")
async def startup_event():
    watcher = get_watcher()
    watcher.start()
    logger.info("OutputWatcher started with server")


@app.on_event("shutdown")
async def shutdown_event():
    watcher = get_watcher()
    watcher.stop()
    logger.info("OutputWatcher stopped with server")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8901)
