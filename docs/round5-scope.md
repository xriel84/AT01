# Round 5 Scope — Resolve Integration
Status: UNBLOCKED (license active, Resolve verified, bridge scaffold committed)
Depends on: Round 4 complete, Resolve license, Resolve activated on /rielt

## Verified (2026-02-25)
- DaVinci Resolve Studio 20.3.1.6 (not 19 — newer than expected)
- Native scripting API: WORKING (DaVinciResolveScript.py)
- pybmd 2026.1.0: INSTALLED but has Python 3.12 type annotation bug (using native API instead)
- resolve_bridge.py scaffold: connect(), get_resolve_info() working; 4 placeholder stubs

## Targets
1. ~~Activate Resolve Studio on /rielt~~ DONE
2. ~~Verify scripting API connection~~ DONE (native API, not pybmd)
3. executor.py: Add Resolve path alongside existing FFmpeg path
4. resolve-paths.json: Auto-discover Resolve project paths
5. Speed test: Same input video, Resolve vs FFmpeg, measure time + quality
6. Implement resolve_bridge.py placeholders (get_current_timeline, get_timeline_clips, export_timeline_markers, import_edl)
7. Tests: 480+ target (459 base + Resolve-specific tests)

## NOT in Round 5
- Goose integration (shelved)
- JP01 frontend changes
- Fusion/Fairlight integration (future rounds)
- Neural Engine features (future rounds)
- pybmd (broken on Python 3.12 — using native DaVinciResolveScript instead)

## Prereqs before starting implementation
- [x] Resolve activated and running on /rielt
- [x] Scripting API verified (native DaVinciResolveScript)
- [x] resolve_bridge.py scaffold committed
- [ ] Test project with timeline + clips creatable via API
- [ ] Ari confirms ready to start implementation

## Resolve installation
- Product: DaVinci Resolve Studio
- Version: 20.3.1.6
- Path: C:\Program Files\Blackmagic Design\DaVinci Resolve\
- Scripting API: C:\ProgramData\Blackmagic Design\DaVinci Resolve\Support\Developer\Scripting\Modules\DaVinciResolveScript.py
- pybmd 2026.1.0 installed (broken — TypeError on `"str" | None` annotation in timeline.py:217)
