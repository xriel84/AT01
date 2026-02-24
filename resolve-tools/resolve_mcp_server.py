"""resolve_mcp_server.py -- MCP server for DaVinci Resolve.

Exposes 16 tools (8 read, 8 write), 4 resources, and an audit log via
the Model Context Protocol.  Can also be used as a CLI for testing
individual tools.

Usage:
    py -3.12 resolve_mcp_server.py --serve              # Start MCP stdio server
    py -3.12 resolve_mcp_server.py --test TOOL_NAME     # Test a single tool
    py -3.12 resolve_mcp_server.py --audit              # Show audit log
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from resolve_common import (
    TOOLS_DIR,
    STAGING_DIR,
    DELIVERY_DIR,
    list_all_sessions,
    read_session_manifest,
    read_sidecar,
    CLIP_COLORS,
)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

AUDIT_LOG = TOOLS_DIR / "mcp_audit.log"


# ---------------------------------------------------------------------------
# Utility functions
# ---------------------------------------------------------------------------

def format_audit_entry(tool: str, params: dict, result: dict) -> str:
    """Format an audit log entry as a JSON string.

    Includes timestamp, tool name, params, and result_summary (truncated
    to 200 chars).
    """
    result_str = json.dumps(result, default=str)
    if len(result_str) > 200:
        result_summary = result_str[:200] + "..."
    else:
        result_summary = result_str

    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "tool": tool,
        "params": params,
        "result_summary": result_summary,
    }
    return json.dumps(entry, default=str)


def log_audit(tool: str, params: dict, result: dict) -> None:
    """Append an audit entry to AUDIT_LOG."""
    entry = format_audit_entry(tool, params, result)
    try:
        AUDIT_LOG.parent.mkdir(parents=True, exist_ok=True)
        with open(AUDIT_LOG, "a", encoding="utf-8") as f:
            f.write(entry + "\n")
    except Exception as exc:
        print(f"[WARN] Audit log write failed: {exc}", file=sys.stderr)


def not_implemented_response(tool: str) -> dict:
    """Return a standard 'not_implemented' error response."""
    return {"error": "not_implemented", "tool": tool}


# ---------------------------------------------------------------------------
# 8 Read tools
# ---------------------------------------------------------------------------

def resolve_list_sessions(**kwargs) -> dict:
    """List all sessions from STAGING_DIR.

    Returns {"sessions": [...], "count": N}.
    """
    sessions = list_all_sessions()
    limit = kwargs.get("limit")
    if limit is not None:
        sessions = sessions[:int(limit)]
    return {"sessions": sessions, "count": len(sessions)}


def resolve_list_feeds(session_id: str, **kwargs) -> dict:
    """Scan STAGING_DIR/{session_id}/ for sidecar JSONs.

    Returns {"feeds": [...], "session_id": str, "count": N}.
    """
    session_dir = STAGING_DIR / session_id
    feeds: list[dict] = []
    if session_dir.is_dir():
        for entry in sorted(session_dir.iterdir()):
            if entry.suffix == ".json" and not entry.name.startswith("_"):
                try:
                    feeds.append(read_sidecar(entry))
                except Exception:
                    pass
    return {"feeds": feeds, "session_id": session_id, "count": len(feeds)}


def resolve_get_metadata(feed_id: str, **kwargs) -> dict:
    """Read a specific feed sidecar by feed_id.

    Searches STAGING_DIR subdirectories for {feed_id}.json.
    Returns the sidecar dict or an error dict.
    """
    if not STAGING_DIR.exists():
        return {"error": "staging_dir_not_found", "feed_id": feed_id}

    for session_dir in STAGING_DIR.iterdir():
        if session_dir.is_dir():
            sidecar_path = session_dir / f"{feed_id}.json"
            if sidecar_path.exists():
                return read_sidecar(sidecar_path)

    return {"error": "feed_not_found", "feed_id": feed_id}


def resolve_list_timelines(**kwargs) -> dict:
    """List timelines from the current Resolve project.

    Requires DaVinci Resolve to be running.
    """
    try:
        from resolve_common import connect_resolve
        resolve = connect_resolve()
    except (ImportError, SystemExit):
        return not_implemented_response("resolve_list_timelines")

    project = resolve.GetProjectManager().GetCurrentProject()
    if project is None:
        return {"error": "no_project", "timelines": []}

    count = project.GetTimelineCount()
    timelines: list[dict] = []
    for i in range(1, count + 1):
        tl = project.GetTimelineByIndex(i)
        if tl:
            timelines.append({
                "index": i,
                "name": tl.GetName(),
                "track_count_video": tl.GetTrackCount("video"),
                "track_count_audio": tl.GetTrackCount("audio"),
            })

    return {"timelines": timelines, "count": len(timelines)}


def resolve_query_markers(timeline_name: str = "", marker_type: str = "", **kwargs) -> dict:
    """Get markers from the active timeline, with optional color filter.

    If timeline_name is provided, attempts to find and switch to that
    timeline first.  marker_type filters by marker color.
    """
    try:
        from resolve_common import connect_resolve
        resolve = connect_resolve()
    except (ImportError, SystemExit):
        return not_implemented_response("resolve_query_markers")

    project = resolve.GetProjectManager().GetCurrentProject()
    if project is None:
        return {"error": "no_project", "markers": []}

    timeline = project.GetCurrentTimeline()
    if timeline is None:
        return {"error": "no_timeline", "markers": []}

    # If a specific timeline is requested, try to switch
    if timeline_name:
        count = project.GetTimelineCount()
        for i in range(1, count + 1):
            tl = project.GetTimelineByIndex(i)
            if tl and tl.GetName() == timeline_name:
                project.SetCurrentTimeline(tl)
                timeline = tl
                break

    markers_raw = timeline.GetMarkers() or {}
    markers: list[dict] = []
    for frame, info in markers_raw.items():
        if marker_type and info.get("color", "").lower() != marker_type.lower():
            continue
        markers.append({
            "frame": frame,
            "color": info.get("color", ""),
            "name": info.get("name", ""),
            "note": info.get("note", ""),
            "duration": info.get("duration", 1),
        })

    return {
        "timeline": timeline.GetName(),
        "markers": markers,
        "count": len(markers),
    }


def resolve_render_status(**kwargs) -> dict:
    """Check if Resolve is currently rendering."""
    try:
        from resolve_common import connect_resolve
        resolve = connect_resolve()
    except (ImportError, SystemExit):
        return not_implemented_response("resolve_render_status")

    project = resolve.GetProjectManager().GetCurrentProject()
    if project is None:
        return {"error": "no_project", "rendering": False}

    rendering = project.IsRenderingInProgress()
    return {"rendering": bool(rendering)}


def resolve_delivery_status(session_id: str = "", **kwargs) -> dict:
    """Read delivery manifest from DELIVERY_DIR.

    If session_id is provided, reads that specific manifest.
    Otherwise, lists all delivery directories.
    """
    if not DELIVERY_DIR.exists():
        return {"error": "delivery_dir_not_found", "deliveries": []}

    if session_id:
        manifest_path = DELIVERY_DIR / session_id / "delivery_manifest.json"
        if manifest_path.exists():
            return read_session_manifest(manifest_path)
        return {"error": "manifest_not_found", "session_id": session_id}

    # List all deliveries
    deliveries: list[dict] = []
    for entry in sorted(DELIVERY_DIR.iterdir()):
        if entry.is_dir():
            manifest_path = entry / "delivery_manifest.json"
            info = {"session_id": entry.name, "has_manifest": manifest_path.exists()}
            if manifest_path.exists():
                try:
                    manifest = read_session_manifest(manifest_path)
                    info["generated_at"] = manifest.get("generated_at", "")
                    info["deliverable_count"] = len(manifest.get("deliverables", []))
                    info["status"] = manifest.get("feedback_loop", {}).get("status", "unknown")
                except Exception:
                    pass
            deliveries.append(info)

    return {"deliveries": deliveries, "count": len(deliveries)}


def resolve_search_clips(query: str, **kwargs) -> dict:
    """Search session metadata by keyword.

    Searches session IDs, feed IDs, feed types, and filenames.
    """
    query_lower = query.lower()
    results: list[dict] = []

    if not STAGING_DIR.exists():
        return {"results": results, "query": query, "count": 0}

    for session_dir in STAGING_DIR.iterdir():
        if not session_dir.is_dir():
            continue

        for entry in sorted(session_dir.iterdir()):
            if entry.suffix != ".json":
                continue
            try:
                data = read_sidecar(entry)
            except Exception:
                continue

            # Search across multiple fields
            searchable = " ".join([
                str(data.get("session_id", "")),
                str(data.get("feed_id", "")),
                str(data.get("feed_type", "")),
                str(data.get("original_filename", "")),
                str(data.get("human_name", "")),
            ]).lower()

            if query_lower in searchable:
                results.append({
                    "file": entry.name,
                    "session_id": data.get("session_id", ""),
                    "feed_id": data.get("feed_id", ""),
                    "feed_type": data.get("feed_type", ""),
                    "original_filename": data.get("original_filename", ""),
                })

    return {"results": results, "query": query, "count": len(results)}


# ---------------------------------------------------------------------------
# 8 Write tools
# ---------------------------------------------------------------------------

def resolve_ingest(path: str, session_name: str, **kwargs) -> dict:
    """Import media via the ingest pipeline.

    Calls resolve_ingest.scan_ingest_dir or process a single file.
    """
    try:
        from resolve_ingest import scan_ingest_dir, ingest_batch, process_file
    except ImportError:
        return not_implemented_response("resolve_ingest")

    import os
    if os.path.isfile(path):
        # Single file ingest
        from resolve_ingest import scan_ingest_dir as _scan
        from resolve_common import FEED_TYPE_MAP
        parent_name = os.path.basename(os.path.dirname(path)).lower()
        feed_type = FEED_TYPE_MAP.get(parent_name, "VRCAM")
        files_by_type = {feed_type: [os.path.abspath(path)]}
    elif os.path.isdir(path):
        files_by_type = scan_ingest_dir(path)
    else:
        return {"error": "path_not_found", "path": path}

    if not files_by_type:
        return {"error": "no_media_found", "path": path}

    # Run ingest without Resolve (session-scoped, no live import)
    ingest_batch(files_by_type, session_name, resolve=None)
    total = sum(len(v) for v in files_by_type.values())
    return {"status": "ingested", "session_name": session_name, "files_processed": total}


def resolve_build_timeline(session_id: str, **kwargs) -> dict:
    """Build a timeline from a session via resolve_scope."""
    try:
        from resolve_scope import build_timeline
    except ImportError:
        return not_implemented_response("resolve_build_timeline")

    if not session_id:
        return {"error": "session_id_required"}

    try:
        build_timeline(session_id, resolve=None)
        return {"status": "dry_run", "session_id": session_id}
    except ValueError as exc:
        return {"error": str(exc)}


def resolve_build_feed_timeline(feed_id: str, **kwargs) -> dict:
    """Build a timeline from a single feed via resolve_scope."""
    try:
        from resolve_scope import build_feed_timeline
    except ImportError:
        return not_implemented_response("resolve_build_feed_timeline")

    if not feed_id:
        return {"error": "feed_id_required"}

    try:
        build_feed_timeline(feed_id, resolve=None)
        return {"status": "dry_run", "feed_id": feed_id}
    except ValueError as exc:
        return {"error": str(exc)}


def resolve_add_marker(
    timeline_name: str,
    tc: str,
    color: str,
    note: str,
    **kwargs,
) -> dict:
    """Place a marker on the active timeline at a given timecode."""
    try:
        from resolve_common import connect_resolve
        resolve = connect_resolve()
    except (ImportError, SystemExit):
        return not_implemented_response("resolve_add_marker")

    project = resolve.GetProjectManager().GetCurrentProject()
    if project is None:
        return {"error": "no_project"}

    timeline = project.GetCurrentTimeline()
    if timeline is None:
        return {"error": "no_timeline"}

    # Switch timeline if needed
    if timeline_name and timeline.GetName() != timeline_name:
        count = project.GetTimelineCount()
        for i in range(1, count + 1):
            tl = project.GetTimelineByIndex(i)
            if tl and tl.GetName() == timeline_name:
                project.SetCurrentTimeline(tl)
                timeline = tl
                break

    # Parse timecode to frame (simplified: assume tc is a frame number if int)
    try:
        frame = int(tc)
    except ValueError:
        # Try HH:MM:SS:FF format
        parts = tc.replace(";", ":").split(":")
        fps = float(timeline.GetSetting("timelineFrameRate") or 24)
        fps_int = int(round(fps))
        if len(parts) == 4:
            h, m, s, f = (int(p) for p in parts)
            frame = int((h * 3600 + m * 60 + s) * fps_int + f)
        else:
            return {"error": "invalid_timecode", "tc": tc}

    success = timeline.AddMarker(frame, color, "MCP", note, 1)
    return {
        "status": "added" if success else "failed",
        "timeline": timeline.GetName(),
        "frame": frame,
        "color": color,
        "note": note,
    }


def resolve_process_markers(timeline_name: str = "", **kwargs) -> dict:
    """Process Green/Red marker pairs into subclips."""
    try:
        from resolve_markers import process_markers
        from resolve_common import connect_resolve
    except ImportError:
        return not_implemented_response("resolve_process_markers")

    try:
        resolve = connect_resolve()
    except SystemExit:
        return not_implemented_response("resolve_process_markers")

    process_markers(resolve, preview=False, session_id=None)
    return {"status": "processed", "timeline": timeline_name or "active"}


def resolve_render(session_id: str, platforms: list[str] | None = None, **kwargs) -> dict:
    """Render deliverables for a session via resolve_deliver."""
    try:
        from resolve_deliver import render_session
    except ImportError:
        return not_implemented_response("resolve_render")

    if not session_id:
        return {"error": "session_id_required"}

    try:
        manifest = render_session(session_id, platforms=platforms)
        return {"status": "rendered", "manifest": manifest}
    except SystemExit:
        return {"error": "resolve_not_available"}


def resolve_set_clip_color(clip_name: str, color: str, **kwargs) -> dict:
    """Search for a clip by name and set its color."""
    try:
        from resolve_common import connect_resolve, get_session_clips
    except ImportError:
        return not_implemented_response("resolve_set_clip_color")

    try:
        resolve = connect_resolve()
    except SystemExit:
        return not_implemented_response("resolve_set_clip_color")

    project = resolve.GetProjectManager().GetCurrentProject()
    if project is None:
        return {"error": "no_project"}

    media_pool = project.GetMediaPool()
    root = media_pool.GetRootFolder()

    # Search all bins for the clip
    def search_folder(folder):
        for clip in (folder.GetClipList() or []):
            if clip.GetName() == clip_name:
                return clip
        for sub in (folder.GetSubFolderList() or []):
            found = search_folder(sub)
            if found:
                return found
        return None

    clip = search_folder(root)
    if clip is None:
        return {"error": "clip_not_found", "clip_name": clip_name}

    clip.SetClipColor(color)
    return {"status": "color_set", "clip_name": clip_name, "color": color}


def resolve_promote_to_selects(clip_name: str, **kwargs) -> dict:
    """Set clip to Green and move to SELECTS bin."""
    try:
        from resolve_common import connect_resolve, find_or_create_bin, CLIP_COLORS
    except ImportError:
        return not_implemented_response("resolve_promote_to_selects")

    try:
        resolve = connect_resolve()
    except SystemExit:
        return not_implemented_response("resolve_promote_to_selects")

    project = resolve.GetProjectManager().GetCurrentProject()
    if project is None:
        return {"error": "no_project"}

    media_pool = project.GetMediaPool()
    root = media_pool.GetRootFolder()

    # Search all bins for the clip
    def search_folder(folder):
        for clip in (folder.GetClipList() or []):
            if clip.GetName() == clip_name:
                return clip
        for sub in (folder.GetSubFolderList() or []):
            found = search_folder(sub)
            if found:
                return found
        return None

    clip = search_folder(root)
    if clip is None:
        return {"error": "clip_not_found", "clip_name": clip_name}

    # Set Green color
    clip.SetClipColor(CLIP_COLORS["select"])

    # Move to SELECTS bin
    selects_bin = find_or_create_bin(media_pool, root, "SELECTS")
    media_pool.MoveClips([clip], selects_bin)

    return {"status": "promoted", "clip_name": clip_name, "color": "Green", "bin": "SELECTS"}


# ---------------------------------------------------------------------------
# TOOLS registry
# ---------------------------------------------------------------------------

TOOLS: dict[str, callable] = {
    # Read tools
    "resolve_list_sessions": resolve_list_sessions,
    "resolve_list_feeds": resolve_list_feeds,
    "resolve_get_metadata": resolve_get_metadata,
    "resolve_list_timelines": resolve_list_timelines,
    "resolve_query_markers": resolve_query_markers,
    "resolve_render_status": resolve_render_status,
    "resolve_delivery_status": resolve_delivery_status,
    "resolve_search_clips": resolve_search_clips,
    # Write tools
    "resolve_ingest": resolve_ingest,
    "resolve_build_timeline": resolve_build_timeline,
    "resolve_build_feed_timeline": resolve_build_feed_timeline,
    "resolve_add_marker": resolve_add_marker,
    "resolve_process_markers": resolve_process_markers,
    "resolve_render": resolve_render,
    "resolve_set_clip_color": resolve_set_clip_color,
    "resolve_promote_to_selects": resolve_promote_to_selects,
}


# ---------------------------------------------------------------------------
# MCP Server
# ---------------------------------------------------------------------------

def start_mcp_server() -> None:
    """Start the MCP server using the mcp Python SDK with stdio transport.

    Registers all 16 tools and 4 resources:
        resolve://sessions
        resolve://session/{id}
        resolve://delivery/{id}
        resolve://analytics/{id}
    """
    try:
        from mcp.server import Server
        from mcp.server.stdio import stdio_server
        from mcp.types import Resource, Tool, TextContent
        import asyncio
    except ImportError:
        print("[ERROR] mcp package not installed.")
        print("        Install with: pip install mcp")
        print("        Or: py -3.12 -m pip install mcp")
        sys.exit(1)

    server = Server("resolve-mcp-server")

    # --- Tool definitions ---
    TOOL_DEFINITIONS = {
        "resolve_list_sessions": {
            "description": "List all ingest sessions from staging directory",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "limit": {"type": "integer", "description": "Max sessions to return"},
                },
            },
        },
        "resolve_list_feeds": {
            "description": "List feeds for a session",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "session_id": {"type": "string", "description": "Session ID"},
                },
                "required": ["session_id"],
            },
        },
        "resolve_get_metadata": {
            "description": "Get metadata for a specific feed",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "feed_id": {"type": "string", "description": "Feed ID"},
                },
                "required": ["feed_id"],
            },
        },
        "resolve_list_timelines": {
            "description": "List timelines from the current Resolve project",
            "inputSchema": {"type": "object", "properties": {}},
        },
        "resolve_query_markers": {
            "description": "Get markers from the active timeline",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "timeline_name": {"type": "string", "description": "Timeline name (optional)"},
                    "marker_type": {"type": "string", "description": "Filter by marker color"},
                },
            },
        },
        "resolve_render_status": {
            "description": "Check if Resolve is currently rendering",
            "inputSchema": {"type": "object", "properties": {}},
        },
        "resolve_delivery_status": {
            "description": "Get delivery status for a session",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "session_id": {"type": "string", "description": "Session ID (optional)"},
                },
            },
        },
        "resolve_search_clips": {
            "description": "Search session metadata by keyword",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search keyword"},
                },
                "required": ["query"],
            },
        },
        "resolve_ingest": {
            "description": "Ingest media files into a session",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "File or directory path"},
                    "session_name": {"type": "string", "description": "Session name"},
                },
                "required": ["path", "session_name"],
            },
        },
        "resolve_build_timeline": {
            "description": "Build a timeline from a session",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "session_id": {"type": "string", "description": "Session ID"},
                },
                "required": ["session_id"],
            },
        },
        "resolve_build_feed_timeline": {
            "description": "Build a timeline from a single feed",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "feed_id": {"type": "string", "description": "Feed ID"},
                },
                "required": ["feed_id"],
            },
        },
        "resolve_add_marker": {
            "description": "Add a marker to the active timeline",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "timeline_name": {"type": "string", "description": "Timeline name"},
                    "tc": {"type": "string", "description": "Timecode or frame number"},
                    "color": {"type": "string", "description": "Marker color"},
                    "note": {"type": "string", "description": "Marker note"},
                },
                "required": ["timeline_name", "tc", "color", "note"],
            },
        },
        "resolve_process_markers": {
            "description": "Process Green/Red marker pairs into subclips",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "timeline_name": {"type": "string", "description": "Timeline name (optional)"},
                },
            },
        },
        "resolve_render": {
            "description": "Render deliverables for a session",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "session_id": {"type": "string", "description": "Session ID"},
                    "platforms": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Platform list (youtube, tiktok, instagram, archive, thumbnails)",
                    },
                },
                "required": ["session_id"],
            },
        },
        "resolve_set_clip_color": {
            "description": "Set the color label on a clip",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "clip_name": {"type": "string", "description": "Clip name"},
                    "color": {"type": "string", "description": "Color name"},
                },
                "required": ["clip_name", "color"],
            },
        },
        "resolve_promote_to_selects": {
            "description": "Set clip to Green and move to SELECTS bin",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "clip_name": {"type": "string", "description": "Clip name"},
                },
                "required": ["clip_name"],
            },
        },
    }

    @server.list_tools()
    async def list_tools():
        tools = []
        for name, defn in TOOL_DEFINITIONS.items():
            tools.append(Tool(
                name=name,
                description=defn["description"],
                inputSchema=defn["inputSchema"],
            ))
        return tools

    @server.call_tool()
    async def call_tool(name: str, arguments: dict):
        if name not in TOOLS:
            result = {"error": "unknown_tool", "tool": name}
        else:
            try:
                result = TOOLS[name](**arguments)
            except Exception as exc:
                result = {"error": str(exc), "tool": name}

        log_audit(name, arguments, result)
        return [TextContent(type="text", text=json.dumps(result, indent=2, default=str))]

    # --- Resource definitions ---
    @server.list_resources()
    async def list_resources():
        resources = [
            Resource(
                uri="resolve://sessions",
                name="All Sessions",
                description="List all ingest sessions",
                mimeType="application/json",
            ),
        ]

        # Dynamic session-scoped resources
        for session in list_all_sessions():
            sid = session.get("session_id", "")
            if sid:
                resources.append(Resource(
                    uri=f"resolve://session/{sid}",
                    name=f"Session: {sid}",
                    description=f"Session details for {sid}",
                    mimeType="application/json",
                ))
                resources.append(Resource(
                    uri=f"resolve://delivery/{sid}",
                    name=f"Delivery: {sid}",
                    description=f"Delivery status for {sid}",
                    mimeType="application/json",
                ))
                resources.append(Resource(
                    uri=f"resolve://analytics/{sid}",
                    name=f"Analytics: {sid}",
                    description=f"Analytics data for {sid}",
                    mimeType="application/json",
                ))
        return resources

    @server.read_resource()
    async def read_resource(uri: str):
        if uri == "resolve://sessions":
            data = resolve_list_sessions()
            return json.dumps(data, indent=2, default=str)

        # Parse session-scoped URIs
        parts = uri.replace("resolve://", "").split("/", 1)
        if len(parts) != 2:
            return json.dumps({"error": "invalid_uri", "uri": uri})

        resource_type, resource_id = parts

        if resource_type == "session":
            data = resolve_list_feeds(resource_id)
            return json.dumps(data, indent=2, default=str)
        elif resource_type == "delivery":
            data = resolve_delivery_status(session_id=resource_id)
            return json.dumps(data, indent=2, default=str)
        elif resource_type == "analytics":
            analytics_path = DELIVERY_DIR / resource_id / "analytics.json"
            if analytics_path.exists():
                with open(analytics_path, "r", encoding="utf-8") as f:
                    return f.read()
            return json.dumps({"error": "analytics_not_found", "session_id": resource_id})
        else:
            return json.dumps({"error": "unknown_resource_type", "type": resource_type})

    # Run the server
    async def run():
        async with stdio_server() as (read_stream, write_stream):
            await server.run(read_stream, write_stream, server.create_initialization_options())

    asyncio.run(run())


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def cli_test_tool(tool_name: str, args_json: str | None = None) -> None:
    """Test a single tool from the CLI."""
    if tool_name not in TOOLS:
        print(f"[ERROR] Unknown tool: {tool_name}")
        print(f"        Available tools: {', '.join(sorted(TOOLS.keys()))}")
        sys.exit(1)

    params = {}
    if args_json:
        try:
            params = json.loads(args_json)
        except json.JSONDecodeError as exc:
            print(f"[ERROR] Invalid JSON args: {exc}")
            sys.exit(1)

    print(f"[TEST] Running {tool_name} with params: {json.dumps(params)}")
    print(f"{'='*60}")

    try:
        result = TOOLS[tool_name](**params)
    except Exception as exc:
        result = {"error": str(exc), "tool": tool_name}

    log_audit(tool_name, params, result)
    print(json.dumps(result, indent=2, default=str))


def cli_show_audit() -> None:
    """Display the audit log."""
    if not AUDIT_LOG.exists():
        print("[INFO] No audit log found.")
        return

    print(f"[AUDIT LOG] {AUDIT_LOG}")
    print(f"{'='*60}")

    with open(AUDIT_LOG, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
                ts = entry.get("timestamp", "?")
                tool = entry.get("tool", "?")
                params = json.dumps(entry.get("params", {}))
                print(f"  [{ts}] {tool} {params}")
            except json.JSONDecodeError:
                print(f"  {line}")


def main() -> None:
    """CLI entry point with mutually exclusive modes."""
    parser = argparse.ArgumentParser(
        description="resolve_mcp_server -- MCP server for DaVinci Resolve.",
    )

    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--serve", action="store_true", help="Start MCP stdio server")
    mode.add_argument("--test", type=str, metavar="TOOL_NAME", help="Test a single tool")
    mode.add_argument("--audit", action="store_true", help="Show audit log")

    parser.add_argument(
        "--args",
        type=str,
        metavar="JSON",
        default=None,
        help="JSON arguments for --test mode",
    )

    args = parser.parse_args()

    if args.serve:
        start_mcp_server()
    elif args.test:
        cli_test_tool(args.test, args.args)
    elif args.audit:
        cli_show_audit()


if __name__ == "__main__":
    main()
