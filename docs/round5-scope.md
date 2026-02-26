# Round 5 Scope — Resolve Integration
Status: UNBLOCKED (license purchased 2026-02-25)
Depends on: Round 4 complete, Resolve license, Resolve activated on /rielt

## Targets
1. Activate Resolve Studio 19 on /rielt with license key (Seat 1)
2. Install pybmd: `py -3.12 -m pip install pybmd`
3. executor.py: Add Resolve path alongside existing FFmpeg path
4. resolve-paths.json: Auto-discover Resolve project paths
5. Speed test: Same input video, Resolve vs FFmpeg, measure time + quality
6. Tests: 480+ target (459 base + Resolve-specific tests)

## NOT in Round 5
- Goose integration (shelved)
- JP01 frontend changes
- Fusion/Fairlight integration (future rounds)
- Neural Engine features (future rounds)

## Prereqs before starting
- [ ] Resolve activated and running on /rielt
- [ ] pybmd installed and importable
- [ ] Test project creatable via API
- [ ] Ari confirms ready to start

## Resolve installation verified
- Path: C:\Program Files\Blackmagic Design\DaVinci Resolve\
- Scripting API: C:\ProgramData\Blackmagic Design\DaVinci Resolve\Support\Developer\Scripting\Modules\DaVinciResolveScript.py
- pybmd available: pybmd 2026.1.0 (not yet installed)
