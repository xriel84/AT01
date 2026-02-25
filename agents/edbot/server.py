"""EdBot FastAPI server — wraps pipeline tools and serves clip viewer UI.

Endpoints:
    GET  /api/health       -> tool status
    POST /api/transcribe   -> run transcription
    POST /api/silence      -> run silence detection
    POST /api/parse        -> run NLP action parser
    POST /api/execute      -> run executor
    GET  /api/chunks       -> cached chunks.json
    GET  /api/silence_map  -> cached silence_map.json
    GET  /api/outputs      -> list output files
    GET  /                 -> serve viewer HTML
    GET  /video/{path}     -> serve video files with byte-range support
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

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

TOOL_NAMES = ["transcribe", "silence_detect", "nlp_action", "executor"]

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
    return result


@app.post("/api/silence")
def api_silence(req: ProcessRequest):
    """Run silence detection and return silence map."""
    result = detect_silence(req.input_path, output_dir=req.output_dir)
    if result.get("error"):
        raise HTTPException(status_code=500, detail=result["error"])
    _cache["silence_map"] = result
    _cache["last_input"] = req.input_path
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
    """Serve the clip viewer HTML page."""
    viewer_path = STATIC_DIR / "viewer.html"
    if not viewer_path.exists():
        return HTMLResponse(
            content="<html><body><h1>EdBot Clip Viewer</h1>"
            "<p>viewer.html not found. Place it in agents/edbot/static/</p>"
            "</body></html>",
            status_code=200,
        )
    return FileResponse(str(viewer_path), media_type="text/html")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8901)
