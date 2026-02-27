---
name: edbot-api
description: Build and test EdBot FastAPI endpoints, tools, and test suites for the AT01 video editing pipeline. Use this skill whenever the user asks to create a new tool, add an endpoint, write tests, run pytest, check server status, or work on any agents/edbot/ code. Also trigger on "add endpoint", "new tool", "write tests", "run tests", "server.py", "FastAPI", tool names like transcribe/silence_detect/portrait_crop, or references to the :8901 server.
---

# EdBot API Patterns

## Server
- Framework: FastAPI
- Port: 8901
- Entry: `C:\AT01\agents\edbot\server.py`
- Shell: `py -3.12` (NEVER bare `python`) | PowerShell only
- Commit prefix: `[aribot]`

## Tool File Structure
```
agents/edbot/tools/{tool_name}.py    ← implementation
agents/edbot/tests/test_{tool_name}.py  ← tests (mocked externals)
```

Every tool function must have:
- Type hints on all parameters and return
- Docstring
- Error → fallback, not crash
- JSON-serializable output
- Mocked external calls in tests

## Endpoint Pattern

```python
@app.post("/api/{tool_name}")
async def api_tool_name(request: Request):
    try:
        body = await request.json()
        # validate required fields
        result = tool_function(**params)
        return JSONResponse(result)
    except FileNotFoundError:
        return JSONResponse({"error": "...", "code": "FILE_NOT_FOUND", "endpoint": "/api/{tool_name}"}, 404)
    except Exception as e:
        return JSONResponse({"error": str(e), "code": "PROCESSING_ERROR", "endpoint": "/api/{tool_name}"}, 500)
```

## Error Response Schema (standardized)
```json
{"error": "description", "code": "ERROR_CODE", "endpoint": "/api/..."}
```
Codes: FILE_NOT_FOUND, INVALID_REQUEST, RESOLVE_OFFLINE, PROCESSING_ERROR, TIMEOUT

## Test Pattern

```python
import pytest
from unittest.mock import patch, MagicMock

def test_tool_name_basic():
    result = tool_function(valid_input)
    assert "expected_key" in result

def test_tool_name_missing_file():
    with pytest.raises(FileNotFoundError):
        tool_function("nonexistent.mp4")

@patch("agents.edbot.tools.tool_name.external_dependency")
def test_tool_name_mocked(mock_dep):
    mock_dep.return_value = {...}
    result = tool_function(input)
    assert result["status"] == "success"
```

## Running Tests
```powershell
cd C:\AT01
py -3.12 -m pytest agents/edbot/tests/ -q              # EdBot only
py -3.12 -m pytest agents/artbot/tests/ -q              # ArtBot only
py -3.12 -m pytest --co -q 2>$null | Select-String "selected"  # Total count
py -3.12 -m pytest -q                                    # Full suite
```

## Current Tool Inventory (28 tools)
EdBot core (23): transcribe, silence_detect, chapter_detect, speaker_detect, portrait_crop, tiktok_chunk, search_transcripts, resolve_bridge (6 fn), analytics_reader, benchmark, shorts tools (8)
Scanner (5): drive_scanner, dropbox_scanner, video_prober, frame_scanner, video_cataloger
ArtBot (7 tools, 68 tests): separate agents/artbot/tools/

## GPU-Aware Transcription (S12)
```python
# gpu_check.py determines config:
# float16 → int8 → medium/int8 → small/cpu
# Audio chunking: >3min → 90s chunks with 5s overlap, merged
# faster-whisper with compute_type from gpu_check
```

## Resolve Bridge Functions
- create_timeline_from_video(project_name, video_path)
- add_markers_from_chapters(timeline, chapters)
- import_edl(project_name, edl_path)
- render_timeline(project_name, timeline_name, output_path, format)
- get_render_status(job_id)
- get_project_info(project_name)

## Adding a New Tool Checklist
1. Create `agents/edbot/tools/{name}.py` with type hints + docstring
2. Create `agents/edbot/tests/test_{name}.py` with ≥3 tests
3. Add endpoint to server.py following error schema
4. Run full test suite — count must increase by expected amount
5. Update API.md with endpoint docs
6. Commit: `[aribot] edbot: add {name} tool — {N} tests`
