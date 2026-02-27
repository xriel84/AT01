---
name: resolve-bridge
description: DaVinci Resolve Studio scripting via pybmd Python wrapper. Timeline creation, marker management, render queue, EDL/XML import. Resolve must be running. Triggers on Resolve automation, timeline, markers, render jobs, EDL import, resolve_bridge.py. 18/18 live tests passing.
---

# DaVinci Resolve Bridge

## Prerequisites
- Resolve Studio MUST be running (not Free edition)
- Env vars set at USER level (not system): RESOLVE_SCRIPT_API, RESOLVE_SCRIPT_LIB, PYTHONPATH
- Runtime path injection in resolve_bridge.py handles the rest

## API Capabilities
- Timeline: create, import (EDL/XML/AAF), export
- Markers: `add_markers_from_chapters(timeline, chapters_list)`
- Render: queue jobs, set codecs, start/stop, get status
- Media pool: import, organize, metadata

## API LIMITATIONS (CANNOT do via scripting)
- Trim, split, or retime clips
- Color wheels/curves/qualifiers
- Playback control (play/pause/scrub)
- Multicam clip creation
- Effect parameter access
- Audio mixer control

## Thread Safety
- Resolve IPC bridge is NOT thread-safe
- ALL API calls must serialize through single worker thread
- FastAPI middleware handles this via queue

## Key Functions
- `create_timeline_from_video(project_name, timeline_name, video_path)`
- `add_markers_from_chapters(timeline, chapters)`
- `import_edl(project, edl_path)`
- `render_timeline(timeline, output_path, codec)`
