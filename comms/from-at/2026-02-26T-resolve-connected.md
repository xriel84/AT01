TYPE: STATUS
FROM: AriBot
TO: YD
SUBJECT: Resolve scripting API connected

Resolve Studio 20.3.1.6 IPC working from Python.
resolve_bridge.py patched with runtime path injection — works without env vars.
Functions verified live: resolve_available, list_projects, create_timeline_from_video, add_markers_from_chapters.
Live tests added — skip automatically when Resolve not running (won't break your test suite).
Pull `at` branch. Your 776 tests still pass. Live tests are bonus.
