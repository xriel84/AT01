# JP01 → AT01: Viewer v8 Frontend Handoff
# Date: 2026-02-26
# Type: HANDOFF

## What's ready
- phone-space-viewer.html v8 Part A (aspect meshes + tabs) — TESTED
- jp01-dev-server.py (port 8080, serves raptor-library.json + video)
- Part B prompt ready (portrait tab + assembly_manifest wiring)
- Part C prompt ready (portrait queue + cross-tab navigation)

## For YD testing
- viewer v8 Part A works standalone — open HTML in Chrome
- needs raptor-library.json (4 entries exist, 96-file batch pending)
- video serving requires jp01-dev-server.py running on 8080

## Branch
jp/contrib-viewer-v8 on NewEccentric/JP01.git
AT01 can fetch: git remote add jp https://github.com/NewEccentric/JP01.git
                git fetch jp jp/contrib-viewer-v8

## Files to pull
- phone-space-viewer.html (~3500 lines)
- jp01-dev-server.py (354 lines)
- raptor-library.json (4 entries)

## What AT needs to do
- Copy viewer + server to AT01 test location
- Run Part B prompt (from project knowledge) against viewer
- YD tests combined result

## Blocked until AT confirms
- AgileLens/edbot repo access for NewEccentric (currently 404)
