# JP Frontend Iterations — Inventory

Copied from `C:\JP01` filesystem on 2026-02-26. No renaming, no reskinning.

## EdBot Office UI Experiments (`C:\JP01\frontend\edbot-office\`)

| File | Layout Concept | Description |
|------|---------------|-------------|
| `experiment-A.html` | Pipeline list + Platform grid | Two-panel split: numbered stage list with status badges + platform cards with per-step indicators |
| `experiment-B.html` | Kanban board | Four columns (Proven / In Progress / Blocked / Designed) with movable cards |
| `experiment-C.html` | Terminal log | Monospace CLI aesthetic with colored prefixes, inline badges, fixed-width platform table |
| `experiment-D.html` | Gauge dashboard | Circular gauge meters + horizontal progress bars per stage + platform cards (JP-defined variant) |
| `experiment-E.html` | Timeline swimlanes | Horizontal Gantt-style bars per pipeline stage with phase-column headers (JP-defined variant) |
| `README-experiments.md` | — | JP's triage notes: design system placeholder, evaluation criteria per experiment |

## Root-Level HTML (`C:\JP01\`)

| File | Description |
|------|-------------|
| `phone-space-viewer.html` | Phone/spatial video viewer — standalone single-file HTML |
| `raptor-library.html` | Raptor library browser/viewer — standalone single-file HTML |

## Notes

- All experiments are standalone single-file HTML — open directly in browser, no build step
- Dark theme using CSS custom properties with placeholder tokens for A9 Office spec swap
- All data is hardcoded/static — no JS fetch, no external deps, no CDN
- No triage decisions made — AT evaluates layout/structure only
- JP-defined variants (D, E) test aggregate metrics and horizontal progression respectively
