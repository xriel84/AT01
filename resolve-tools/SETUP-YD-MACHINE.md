# YD Machine Setup — EdBot Pipeline

Run these in PowerShell on YD's machine. Resolve Studio must already be installed.

## 1. Verify Python 3.12
```powershell
py -3.12 --version
```
If missing: install from python.org, check "Add to PATH", use 3.12.x

## 2. Set Resolve API environment variables
Run as Admin or add to system env permanently:
```powershell
[System.Environment]::SetEnvironmentVariable("RESOLVE_SCRIPT_API", "C:\ProgramData\Blackmagic Design\DaVinci Resolve\Support\Developer\Scripting", "User")
[System.Environment]::SetEnvironmentVariable("RESOLVE_SCRIPT_LIB", "C:\Program Files\Blackmagic Design\DaVinci Resolve\fusionscript.dll", "User")
$currentPath = [System.Environment]::GetEnvironmentVariable("PYTHONPATH", "User")
[System.Environment]::SetEnvironmentVariable("PYTHONPATH", "$currentPath;C:\ProgramData\Blackmagic Design\DaVinci Resolve\Support\Developer\Scripting\Modules\", "User")
```
RESTART PowerShell after this step.

## 3. Verify FFmpeg
```powershell
ffmpeg -version
```
If missing: install via `winget install Gyan.FFmpeg` or download from ffmpeg.org, add to PATH.

## 4. Clone and checkout
```powershell
cd C:\NB11
git clone https://github.com/xriel84/AT01.git
cd AT01
```

## 5. Create pipeline directories
```powershell
"resolve-ingest\livestream","resolve-ingest\conference","resolve-ingest\raw","resolve-staging","resolve-archive","resolve-delivery","resolve-tools\logs" | ForEach-Object {
    New-Item -ItemType Directory -Force -Path "C:\NB11\$_"
}
```

## 6. Copy scripts to working location
```powershell
Copy-Item -Path "C:\NB11\AT01\resolve-tools\*" -Destination "C:\NB11\resolve-tools\" -Recurse -Force
```

## 7. Preflight test (Resolve must be open)
```powershell
cd "C:\Program Files\Blackmagic Design\DaVinci Resolve"
py -3.12 -c "import DaVinciResolveScript as dvr; r = dvr.scriptapp('Resolve'); print('OK:', r.GetVersionString())"
py -3.12 C:\NB11\resolve-tools\resolve_ingest.py --list
py -3.12 C:\NB11\resolve-tools\resolve_scope.py --list
```

## 8. Done
Read `C:\NB11\resolve-tools\README-YD.md` and start using .ps1 wrappers.
