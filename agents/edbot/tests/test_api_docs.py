"""Tests for API.md completeness and quality."""

import re
import sys
from pathlib import Path

import pytest

_tools_dir = str(Path(__file__).resolve().parent.parent / "tools")
if _tools_dir not in sys.path:
    sys.path.insert(0, _tools_dir)

API_MD = Path(__file__).resolve().parent.parent / "API.md"
SERVER_PY = Path(__file__).resolve().parent.parent / "server.py"


def _read_api_md():
    assert API_MD.exists(), f"API.md not found at {API_MD}"
    return API_MD.read_text(encoding="utf-8")


def _read_server_py():
    return SERVER_PY.read_text(encoding="utf-8")


def _extract_routes_from_server():
    """Parse server.py for @app.{method}(path) decorators."""
    text = _read_server_py()
    # Match @app.get("/path"), @app.post("/path"), @app.websocket("/path")
    pattern = r'@app\.(get|post|websocket)\(\s*"([^"]+)"'
    return [(method.upper(), path) for method, path in re.findall(pattern, text)]


class TestApiDocs:
    def test_api_md_exists(self):
        """API.md file exists in agents/edbot/."""
        assert API_MD.exists()

    def test_api_md_covers_all_endpoints(self):
        """Parse server.py for @app routes, verify each appears in API.md."""
        api_text = _read_api_md()
        routes = _extract_routes_from_server()
        assert len(routes) >= 30, f"Expected 30+ routes, found {len(routes)}"
        missing = []
        for method, path in routes:
            # Normalize path params: /api/resolve/render/{job_id} -> /api/resolve/render/
            normalized = re.sub(r"\{[^}]+\}", "", path).rstrip("/")
            if normalized not in api_text and path not in api_text:
                missing.append(f"{method} {path}")
        assert not missing, f"Endpoints missing from API.md: {missing}"

    def test_api_md_has_curl_examples(self):
        """Every endpoint section contains a curl example."""
        api_text = _read_api_md()
        # Split by endpoint headers (## GET/POST/WS)
        sections = re.split(r"^### ", api_text, flags=re.MULTILINE)
        # Skip the preamble and non-endpoint sections
        endpoint_sections = [
            s for s in sections
            if s and re.match(r"(GET|POST|WS) /", s)
        ]
        assert len(endpoint_sections) >= 30, (
            f"Expected 30+ endpoint sections, found {len(endpoint_sections)}"
        )
        missing_curl = []
        for section in endpoint_sections:
            header = section.split("\n")[0].strip()
            if "curl" not in section and "WebSocket" not in section and "ws://" not in section:
                missing_curl.append(header)
        assert not missing_curl, f"Sections missing curl examples: {missing_curl}"

    def test_api_md_has_error_responses(self):
        """Every POST endpoint documents error response format."""
        api_text = _read_api_md()
        sections = re.split(r"^### ", api_text, flags=re.MULTILINE)
        post_sections = [
            s for s in sections
            if s and s.startswith("POST /")
        ]
        assert len(post_sections) >= 15, (
            f"Expected 15+ POST sections, found {len(post_sections)}"
        )
        missing_errors = []
        for section in post_sections:
            header = section.split("\n")[0].strip()
            if "Error" not in section and "error" not in section.lower():
                missing_errors.append(header)
        assert not missing_errors, f"POST sections missing error docs: {missing_errors}"
