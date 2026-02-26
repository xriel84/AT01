# JP01 → AT01: Viewer v8 Part B Ready
# Date: 2026-02-26
# Type: STATUS

Part B applied to phone-space-viewer.html on jp/contrib-viewer-v8.

What's new:
- Portrait tab now ingests assembly_manifest.json
- File-drop or fetch from localhost:8080 (cascade with relative fallback)
- 3 test entries in assembly_manifest.json (tiktok, ig_reels, ig_feed)
- Portrait phones render in 3-wide grid with correct aspect meshes
- SOURCE link in zoom panel (read-only, Part C makes clickable)
- Port audit complete: all JP01 data URLs use 8080, AT01 stays 8000

For YD testing:
1. git fetch jp jp/contrib-viewer-v8
2. Copy phone-space-viewer.html to AT01 test dir
3. Open in Chrome — SOURCE tab has 4 raptor-library clips
4. Drop assembly_manifest.json onto viewer OR serve from 8080
5. Switch to PORTRAIT tab — 3 test phones appear
6. Zoom portrait phone — shows SOURCE: RH_XXX

Part C (queue + cross-tab nav) is next. Blocked until YD confirms B works.
