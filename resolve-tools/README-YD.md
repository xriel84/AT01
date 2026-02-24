# EdBot Quick Start — Yidan

## Before anything
1. Open DaVinci Resolve Studio (must be running before any scripts)
2. Open the Agile Lens project in Resolve

## Drop footage
Put your .mp4 files in one of these folders:
- `C:\NB11\resolve-ingest\livestream\` — for livestream recordings
- `C:\NB11\resolve-ingest\conference\` — for conference recordings
- `C:\NB11\resolve-ingest\raw\` — for everything else

## One-click scripts (double-click these)
| Script | What it does |
|--------|-------------|
| `run_ingest.ps1` | Scans for new footage, validates, imports to Resolve |
| `run_scope_list.ps1` | Shows all loaded scenes and clip counts |
| `run_build_timeline.ps1` | Builds a Resolve timeline from a scene (asks which one) |

## Clip colors in Resolve
- Blue = not reviewed yet
- Green = approved
- Yellow = needs another look
- Red = rejected
- Purple = b-roll
- Orange = needs fixing

## Rules
- Only .mp4 files (if you have .mkv, the script auto-converts)
- OBS recordings: set to NVENC + Constant Frame Rate + MP4 in OBS settings
- Only one person can have the same Resolve project open at a time
- Originals are always backed up automatically — nothing gets deleted

## Something broke?
Copy the full error message and paste it to Claude in your EdBot project.
Claude has all the context to diagnose it.
