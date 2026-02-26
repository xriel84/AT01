"""Resolve bridge tests — connection + placeholder stubs.

Tests that require a running Resolve instance are marked with
@pytest.mark.skipif and will be skipped in CI or when Resolve is not open.
"""

import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

_tools_dir = str(Path(__file__).resolve().parent.parent / "agents" / "edbot" / "tools")
if _tools_dir not in sys.path:
    sys.path.insert(0, _tools_dir)

from resolve_bridge import (
    connect,
    get_resolve_info,
    get_current_timeline,
    get_timeline_clips,
    export_timeline_markers,
    import_edl,
)


# ---------------------------------------------------------------------------
# Helper: detect if Resolve is running
# ---------------------------------------------------------------------------

def _resolve_available() -> bool:
    """Check if Resolve scripting API is reachable."""
    try:
        connect()
        return True
    except (RuntimeError, ImportError, OSError):
        return False


_HAS_RESOLVE = _resolve_available()


# ---------------------------------------------------------------------------
# 1. test_import
# ---------------------------------------------------------------------------

def test_import():
    """resolve_bridge module imports without error."""
    import resolve_bridge
    assert hasattr(resolve_bridge, "connect")
    assert hasattr(resolve_bridge, "get_resolve_info")


# ---------------------------------------------------------------------------
# 2. test_connect_mock
# ---------------------------------------------------------------------------

def test_connect_mock():
    """connect() returns Resolve object when scriptapp succeeds."""
    mock_resolve = MagicMock()
    mock_dvr = MagicMock()
    mock_dvr.scriptapp.return_value = mock_resolve

    with patch.dict("sys.modules", {"DaVinciResolveScript": mock_dvr}):
        result = connect()
    assert result is mock_resolve


# ---------------------------------------------------------------------------
# 3. test_connect_none_raises
# ---------------------------------------------------------------------------

def test_connect_none_raises():
    """connect() raises RuntimeError when scriptapp returns None."""
    mock_dvr = MagicMock()
    mock_dvr.scriptapp.return_value = None

    with patch.dict("sys.modules", {"DaVinciResolveScript": mock_dvr}):
        with pytest.raises(RuntimeError, match="Resolve running"):
            connect()


# ---------------------------------------------------------------------------
# 4. test_get_resolve_info_mock
# ---------------------------------------------------------------------------

def test_get_resolve_info_mock():
    """get_resolve_info() returns product and version dict."""
    mock_resolve = MagicMock()
    mock_resolve.GetProductName.return_value = "DaVinci Resolve Studio"
    mock_resolve.GetVersion.return_value = [20, 3, 1, 6, ""]

    mock_dvr = MagicMock()
    mock_dvr.scriptapp.return_value = mock_resolve

    with patch.dict("sys.modules", {"DaVinciResolveScript": mock_dvr}):
        info = get_resolve_info()

    assert info["product"] == "DaVinci Resolve Studio"
    assert info["version"] == [20, 3, 1, 6, ""]
    assert info["version_string"] == "20.3.1.6"


# ---------------------------------------------------------------------------
# 5. test_connect_live (requires Resolve running)
# ---------------------------------------------------------------------------

@pytest.mark.skipif(not _HAS_RESOLVE, reason="Resolve not running")
def test_connect_live():
    """Live connection to Resolve returns a non-None object."""
    resolve = connect()
    assert resolve is not None
    assert resolve.GetProductName() is not None


# ---------------------------------------------------------------------------
# 6. test_get_resolve_info_live (requires Resolve running)
# ---------------------------------------------------------------------------

@pytest.mark.skipif(not _HAS_RESOLVE, reason="Resolve not running")
def test_get_resolve_info_live():
    """Live get_resolve_info returns real version data."""
    info = get_resolve_info()
    assert "DaVinci Resolve" in info["product"]
    assert len(info["version"]) >= 4
    assert isinstance(info["version_string"], str)


# ---------------------------------------------------------------------------
# 7-10. Placeholder function stubs (raise NotImplementedError)
# ---------------------------------------------------------------------------

def test_get_current_timeline_not_implemented():
    """get_current_timeline raises NotImplementedError (Round 5 stub)."""
    with pytest.raises(NotImplementedError, match="Round 5"):
        get_current_timeline()


def test_get_timeline_clips_not_implemented():
    """get_timeline_clips raises NotImplementedError (Round 5 stub)."""
    with pytest.raises(NotImplementedError, match="Round 5"):
        get_timeline_clips(None)


def test_export_timeline_markers_not_implemented():
    """export_timeline_markers raises NotImplementedError (Round 5 stub)."""
    with pytest.raises(NotImplementedError, match="Round 5"):
        export_timeline_markers(None)


def test_import_edl_not_implemented():
    """import_edl raises NotImplementedError (Round 5 stub)."""
    with pytest.raises(NotImplementedError, match="Round 5"):
        import_edl(None, "test.edl")
