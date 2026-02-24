# EdBot — Scan and import new footage
# Double-click to run. Resolve must be open first.
cd "C:\Program Files\Blackmagic Design\DaVinci Resolve"
py -3.12 C:\NB11\resolve-tools\resolve_ingest.py --once
Read-Host "Press Enter to close"
