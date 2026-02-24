# EdBot Office — UI Experiments

Frontend triage batch. Each file is a standalone `.html` — open directly in browser, no build step.

**Design system:** PLACEHOLDER dark theme (A9 Office spec not available). All color values use CSS custom properties with `/* PLACEHOLDER: A9 ... */` comments for easy token swap when spec arrives.

**Data:** All pipeline/platform status is hardcoded static data matching the current state snapshot.

---

## Experiments

| File | Layout Concept | What AT Should Evaluate |
|------|---------------|------------------------|
| `experiment-A.html` | **Pipeline list + Platform grid** | Two-panel split: left = numbered stage list with status badges, right = platform cards with per-step indicators. Does the two-panel scan well? Is the stage list dense enough or too sparse? |
| `experiment-B.html` | **Kanban board** | Four columns: Proven / In Progress / Blocked / Designed. Cards move between columns as status changes. Does the kanban mental model match how AT thinks about pipeline state? Is "Blocked" useful as its own column? |
| `experiment-C.html` | **Terminal log** | Monospace output aesthetic — status as scrolling log lines with colored prefixes and inline badges. Platform table in fixed-width columns. Does the CLI feel match the pipeline's technical nature? Is it readable enough for non-terminal users? |
| `experiment-D.html` | **Gauge dashboard** | Top row: four circular gauge meters (stages proven, platforms active, visual filter pass rate, renders complete). Below: horizontal progress bars per stage + platform cards. Do the gauges add quick-glance value or are they noise? |
| `experiment-E.html` | **Timeline swimlanes** | Horizontal Gantt-style bars per pipeline stage showing progression from Designed → Proven. Platform section uses step grid. Does the horizontal metaphor convey progress better than vertical lists? Is the phase-column header useful? |

---

## Shared Elements (all experiments)

- **Blocker banner**: Red alert bar at top showing active blocker (Resolve crashed)
- **Dark theme**: CSS variables ready for A9 token replacement
- **Static data**: No JS fetch — all status hardcoded for triage
- **Single-file**: No external deps, no CDN, no build step
- **Responsive**: Basic breakpoints included

## JP-Defined Variants (D & E)

- **D (Gauge Dashboard)**: JP rationale — tests whether aggregate summary metrics (gauges) provide faster situational awareness than item-by-item lists
- **E (Timeline Swimlanes)**: JP rationale — tests whether horizontal progression conveys pipeline state better than vertical list/card layouts, especially for showing how far each stage has advanced

## Triage Notes for AT

- No winners selected — AT triages
- All copy is generic/structural — no creative content decisions made
- Color palette is placeholder — swap CSS variables when A9 spec is available
- These are layout/structure experiments only
