"""EdBot FastAPI server — wraps pipeline tools and serves clip viewer UI.

Endpoints:
    GET  /api/health          -> tool status
    POST /api/transcribe      -> run transcription
    POST /api/silence         -> run silence detection
    POST /api/parse           -> run NLP action parser
    POST /api/execute         -> run executor
    GET  /api/chunks          -> cached chunks.json
    GET  /api/silence_map     -> cached silence_map.json
    GET  /api/outputs         -> list output files
    GET  /api/chapters        -> run chapter detection
    GET  /api/speakers        -> run speaker detection
    POST /api/portrait_crop   -> crop video to portrait
    POST /api/tiktok          -> generate TikTok chunks
    GET  /api/session         -> current session state
    GET  /api/clips_manifest  -> cached clips manifest
    GET  /api/gpu_status      -> CUDA availability check
    GET  /                    -> serve viewer HTML
    GET  /video/{path}        -> serve video files with byte-range support
"""

import mimetypes
import os
import sys
from pathlib import Path
from typing import Any

import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, Response, StreamingResponse
from pydantic import BaseModel

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

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

TOOL_NAMES = ["transcribe", "silence_detect", "nlp_action", "executor",
              "chapter_detect", "speaker_detect", "portrait_crop", "tiktok_chunk"]

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


@app.post("/api/transcribe")
def api_transcribe(req: ProcessRequest):
    """Run transcribe_video and return chunks data."""
    result = transcribe_video(req.input_path, req.output_dir)
    if result.get("error"):
        raise HTTPException(status_code=500, detail=result["error"])
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
        raise HTTPException(status_code=500, detail=result["error"])
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
        raise HTTPException(status_code=500, detail=result.get("error", "execution failed"))
    return result


@app.get("/api/chunks")
async def api_chunks():
    """Return last cached chunks result."""
    if _cache["chunks"] is None:
        raise HTTPException(status_code=404, detail="no chunks cached — run /api/transcribe first")
    return _cache["chunks"]


@app.get("/api/silence_map")
async def api_silence_map():
    """Return last cached silence map."""
    if _cache["silence_map"] is None:
        raise HTTPException(status_code=404, detail="no silence map cached — run /api/silence first")
    return _cache["silence_map"]


@app.get("/api/outputs")
async def api_outputs():
    """List files in the output directory."""
    if not OUTPUT_DIR.exists():
        return {"files": []}
    files = []
    for f in OUTPUT_DIR.iterdir():
        if f.is_file():
            files.append({
                "name": f.name,
                "size": f.stat().st_size,
                "path": str(f),
            })
    return {"files": files}


# ---------------------------------------------------------------------------
# Round 3 endpoints
# ---------------------------------------------------------------------------

@app.get("/api/chapters")
def api_chapters():
    """Run chapter detection on cached chunks + silence_map."""
    chunks = _session.get("chunks") or (_cache.get("chunks") or {}).get("chunks")
    if not chunks:
        raise HTTPException(status_code=404, detail="no chunks — run /api/transcribe first")
    silence_map = _session.get("silence_map") or _cache.get("silence_map")
    chapters = detect_chapters(chunks, silence_map=silence_map)
    _session["chapters"] = chapters
    return {"chapters": chapters}


@app.get("/api/speakers")
def api_speakers():
    """Run speaker detection on session video."""
    video_path = _session.get("video_path") or _cache.get("last_input")
    if not video_path:
        raise HTTPException(status_code=404, detail="no video path — load a video first")
    chunks = _session.get("chunks") or (_cache.get("chunks") or {}).get("chunks")
    result = detect_speakers(video_path, chunks=chunks)
    if result.get("error"):
        raise HTTPException(status_code=500, detail=result["error"])
    _session["speaker_map"] = result
    return result


class LabelRequest(BaseModel):
    labels: dict[str, str]  # {"SPEAKER_0": "Ari", "SPEAKER_1": "Alex"}


@app.post("/api/label_speakers")
def api_label_speakers(req: LabelRequest):
    """Update speaker labels in session speaker_map."""
    speaker_map = _session.get("speaker_map")
    if speaker_map is None:
        raise HTTPException(status_code=404, detail="no speaker map — run /api/speakers first")
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
    input_path = req.input_path or _session.get("video_path") or _cache.get("last_input")
    if not input_path:
        raise HTTPException(status_code=400, detail="no input path")
    result = portrait_crop(input_path, req.output_dir, method=req.method, start=req.start, end=req.end)
    if result.get("status") == "error":
        raise HTTPException(status_code=500, detail=result.get("error", "crop failed"))
    return result


@app.post("/api/tiktok")
def api_tiktok(req: TikTokRequest):
    """Generate TikTok chunks from video."""
    input_path = req.input_path or _session.get("video_path") or _cache.get("last_input")
    if not input_path:
        raise HTTPException(status_code=400, detail="no input path")
    chapters = _session.get("chapters")
    if not chapters:
        # Auto-detect chapters first
        chunks = _session.get("chunks") or (_cache.get("chunks") or {}).get("chunks")
        if not chunks:
            raise HTTPException(status_code=404, detail="no chunks — run /api/transcribe first")
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
        raise HTTPException(status_code=404, detail="no clips manifest — run /api/tiktok first")
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
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8901)
