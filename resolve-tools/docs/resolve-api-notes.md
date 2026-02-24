# DaVinci Resolve Scripting API — Quirks & Patterns

Notes extracted from the resolve-tools codebase. These are the non-obvious behaviors that cause bugs.

## Connection

```python
# Standard connection sequence (resolve_common.connect_resolve)
RESOLVE_MODULES_PATH = r"C:\ProgramData\Blackmagic Design\DaVinci Resolve\Support\Developer\Scripting\Modules"
sys.path.insert(0, RESOLVE_MODULES_PATH)
import DaVinciResolveScript as dvr
resolve = dvr.scriptapp("Resolve")
```

**Gotchas:**
- `scriptapp("Resolve")` returns None if Resolve isn't running OR if External Scripting is disabled
- Check: Preferences > System > General > External Scripting = "Local"
- `connect_resolve()` calls `sys.exit(1)` on failure. Callers wanting graceful degradation must catch `SystemExit`
- Environment variables that matter: RESOLVE_SCRIPT_API, RESOLVE_SCRIPT_LIB, PYTHONPATH

## Null Returns Everywhere

**GetSubFolderList() returns None, not empty list**, when a folder has no subfolders:
```python
# WRONG - will crash on None
for sub in parent_folder.GetSubFolderList():

# RIGHT - guard against None
for sub in (parent_folder.GetSubFolderList() or []):
```

Same pattern applies to: GetClipList(), GetItemListInTrack(), ImportMedia()

## Bin (Folder) Operations

```python
media_pool = project.GetMediaPool()
root = media_pool.GetRootFolder()

# Find or create - must manually search
for sub in (root.GetSubFolderList() or []):
    if sub.GetName() == "RAW FOOTAGE":
        raw_folder = sub
        break
else:
    raw_folder = media_pool.AddSubFolder(root, "RAW FOOTAGE")

# Set current folder before importing
media_pool.SetCurrentFolder(target_folder)
imported_clips = media_pool.ImportMedia(list_of_file_paths)
```

**Gotchas:**
- No recursive search API. Must traverse bin tree manually for clip search
- AddSubFolder returns the new folder object
- ImportMedia takes a list of absolute file paths, returns list of clips or None

## Clip Colors

Colors are **string names, case-sensitive**: "Blue", "Green", "Yellow", "Red", "Purple", "Orange", etc.

```python
clip.SetClipColor("Blue")  # Works
clip.SetClipColor("blue")  # May not work — case matters
```

## Timeline Creation

```python
# Method 1: From clips (preferred)
timeline = media_pool.CreateTimelineFromClips("MyTimeline", clip_list)

# Method 2: Empty + append (fallback when Method 1 fails)
timeline = media_pool.CreateEmptyTimeline("MyTimeline")
media_pool.AppendToTimeline(clip_list)
```

**Gotchas:**
- CreateTimelineFromClips can fail silently (returns None). Always have fallback
- The codebase uses this two-step pattern in resolve_scope.py and resolve_markers.py
- Must call project.SetCurrentTimeline(tl) before reading markers/clips from a specific timeline

## Markers

```python
# Read markers from current timeline
markers = timeline.GetMarkers()
# Returns: {frame_int: {"color": str, "name": str, "note": str, "duration": int, ...}}

# Add marker
timeline.AddMarker(frame, color, name, note, duration)
# duration is in frames, minimum 1
```

**Gotchas:**
- Marker dict is keyed by **frame number** (int), not timecode
- To convert timecode to frames: parse HH:MM:SS:FF, multiply by FPS
- Default FPS if GetSetting("timelineFrameRate") fails: 24
- Color filtering must be done client-side (no API filter parameter)

## Tracks and Clips in Timeline

```python
track_count = timeline.GetTrackCount("video")  # or "audio"
for i in range(1, track_count + 1):  # 1-indexed!
    items = timeline.GetItemListInTrack("video", i)
    for item in (items or []):
        name = item.GetName()
```

**Gotcha:** Track indices are **1-based**, not 0-based.

## Rendering

```python
project.SetRenderSettings({
    "FormatWidth": 1920,
    "FormatHeight": 1080,
    "TargetDir": output_path,
})
job_id = project.AddRenderJob()
project.StartRendering(job_id)

# Poll for completion
while project.IsRenderingInProgress():
    time.sleep(1)
```

**Gotchas:**
- SetRenderSettings is **per-call**, not persistent across renders
- Must call SetRenderSettings before each AddRenderJob if settings differ
- IsRenderingInProgress() is blocking-poll only — no async/callback
- Render presets are project-level, not system-level

## Smart Bins

**Not supported** by the scripting API (even in Studio). resolve_template.setup_smart_bins() only prints definitions for manual creation. This is documented in the code as "future API expansion."

## FFmpeg/FFprobe Timeouts

Used in resolve_common and resolve_detect_test:
- ffprobe validation: 30s
- Stream copy remux: 600s (10 min)
- Re-encode fallback: 1800s (30 min)
- Detection analysis: 300s (5 min)
