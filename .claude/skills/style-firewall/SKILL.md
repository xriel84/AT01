---
name: style-firewall
description: Enforce AT01/JP01 visual style separation and file prefix conventions. Use this skill whenever creating, renaming, or reviewing files with at_ or jp_ prefixes, working on ComfyUI prompts or workflows, generating assets, reviewing git diffs for cross-contamination, or when any creative styling decision touches AT01 or JP01 repos. Trigger on "style check", "prefix", "Art Deco", "Steampunk", "cross-contamination", or any file naming question involving at_/jp_/al_ prefixes.
---

# Style Firewall — AT01 ↔ JP01

## Prefix Rules (NON-NEGOTIABLE)

| Prefix | Repo | Visual Style | Time of Day | Mood | Typography |
|--------|------|-------------|-------------|------|------------|
| `at_` | AT01 (xriel84, PUBLIC) | Constructivist Art Deco | Night | Dark, dramatic, theatrical | Poiret One + Playfair Display + JetBrains Mono |
| `jp_` | JP01 (NewEccentric, PRIVATE) | Steampunk | Day | Cheerful, warm, inviting | (JP defines) |

### Legacy: `al_` → `at_`
The `al_` prefix (Agile Lens) was renamed to `at_` in S15. All new files use `at_`. Existing `al_` files in codebase references should be updated when touched.

## Enforcement Rules

1. **AT01 repo** must contain ZERO:
   - `jp_` prefixed files or references
   - Steampunk visual references
   - JP01 file paths in committed code
   - NewEccentric account references in public materials

2. **JP01 repo** must contain ZERO:
   - `at_` prefixed files in its own asset pipeline
   - Art Deco visual references in JP-owned code
   - (JP CAN reference AT01 upstream code it forked — that's the fork relationship)

3. **Bridge branches** are the ONLY location where both prefixes may coexist

4. **ComfyUI Save node prefix** must match output folder:
   - AT01 workflows: `at/at_{subject}_{shot}_{action}`
   - JP01 workflows: `jp/jp_{subject}_{shot}_{action}`

## Pre-Commit Validation

```powershell
# Check for jp_ contamination in AT01 staged files
cd C:\AT01
git diff --cached --name-only | Select-String "jp_"
# Should return ZERO matches

# Check for jp_ string references in AT01 code
Select-String -Path "agents\**\*.py" -Pattern "jp_" -Recurse -SimpleMatch
# Should return ZERO matches (except bridge-config.json which documents the rule)
```

## ComfyUI Prompt Style Tokens

### AT01 (Art Deco)
Positive: `art deco, constructivist, geometric, gold accents, dramatic lighting, night scene, noir, theatrical`
Negative: `steampunk, gears, brass, victorian, daytime, cheerful, warm tones, rustic`

### JP01 (Steampunk)  
Positive: `steampunk, brass gears, victorian, warm lighting, daytime, cheerful, copper, mechanical`
Negative: `art deco, geometric, gold, noir, night, dark, theatrical, constructivist`

## Palette

### AT01
- Primary: Deep blacks, gold (#c9a84c), cream (#f5e6c8), dark blues
- Accent: Gold metallic, warm amber
- Background: Dark/black

### JP01
- (JP defines — AT01 does not dictate JP01 creative choices)

## Audit Command

```powershell
# Full cross-contamination audit
cd C:\AT01
$violations = @()
Get-ChildItem -Recurse -Include *.py,*.js,*.html,*.json -Exclude node_modules,*.git* | 
    Select-String -Pattern "jp_|steampunk|NewEccentric" -SimpleMatch | 
    Where-Object { $_.Path -notmatch "bridge-config|comms[\\/]private|\.gitignore" } |
    ForEach-Object { $violations += $_.ToString() }
if ($violations.Count -eq 0) { Write-Host "CLEAN — no cross-contamination" }
else { Write-Host "VIOLATIONS:"; $violations }
```
