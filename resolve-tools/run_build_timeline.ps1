# EdBot — Build timeline for a scene
# Double-click to run. Resolve must be open first.
$scene = Read-Host "Enter Scene ID (e.g. LIVESTRM_20250115_001)"
if ([string]::IsNullOrWhiteSpace($scene)) {
    Write-Host "No Scene ID entered. Listing available scenes:"
    cd "C:\Program Files\Blackmagic Design\DaVinci Resolve"
    py -3.12 C:\NB11\resolve-tools\resolve_scope.py --list
} else {
    cd "C:\Program Files\Blackmagic Design\DaVinci Resolve"
    py -3.12 C:\NB11\resolve-tools\resolve_scope.py --build $scene
}
Read-Host "Press Enter to close"
