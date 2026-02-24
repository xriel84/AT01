# NB11 Session Handoff — 2026-02-24

## Dual-Track Architecture

NB11 runs two parallel content tracks through the same EdBot toolchain:

| Track | Repo | Account | Content | Audience | Isolation |
|-------|------|---------|---------|----------|-----------|
| AT/EdBot | xriel84/AT01 | xriel84 | AgileLens RSC + streams | AL team + YD | Shared with AgileLens |
| JP/EdBot | NewEccentric/JP01 | NewEccentric | raptor-history portfolio | Ari only | PRIVATE — never shared |

### Information Flow Rules

```
    AgileLens (Alex, Sam, Kevin, YD)
         ^
         | content + status
         |
    AT01 (xriel84) <---- EdBot tools are identical ----> JP01 (NewEccentric)
         |                                                    |
         | technical improvements (one-way AT->JP)            |
         |                                                    |
    RSC footage                                    raptor-history footage
    AgileLens streams                              Personal portfolio
         |                                                    |
         +-- NEVER CROSSES ---------------------- NEVER CROSSES -+
```

- AT discovers EdBot improvement -> commits to AT01 -> JP pulls from upstream
- JP content -> never touches AT01, AgileLens, or any shared channel
- AT content -> never touches JP01
- AT is the only bridge between both tracks

### Who Sees What

| Person | AT01 repo | JP01 repo | RSC content | raptor-history content | EdBot tools |
|--------|-----------|-----------|-------------|----------------------|-------------|
| AT (Ari) | push | push | yes | yes | both |
| YD | via AL | no | yes | no | AT01 copy |
| Alex/Sam | via AL | no | yes | no | AT01 copy |
| Kevin | via AL | no | yes | no | AT01 copy |
| JP (Jasper session) | no | push | no | yes | JP01 copy |

## What Changed Since Last Handoff (2026-02-23 Late)

### Already committed:
- Stages 5/7/8 built + tested: silence_remove.py, subtitle_gen.py, subtitle_burn.py
- 209/209 tests green on AT01
- API name corrections documented (actual function signatures != design doc)
- YD runbook created (3-part, gated)
- pysubs2, soundfile, librosa installed on AT
- Resolve Studio activation instructions added to SETUP-YD-MACHINE.md
- ENVIRONMENT-STATUS.md + pytest.ini added

### New this session:
- raptor-history track formalized — JP01 handles personal portfolio content
- ArtBot replaces SBot — security detail delayed, art output prioritized
- EdBot T1 triage designed — autonomous clip scoring + keep/trash pipeline
- Content isolation rules codified — RSC != raptor-history, enforced at repo level

## Current State

| Item | Status |
|------|--------|
| AT01 tests | 209/209 green (commit 44f7d02) |
| Stages 5/7/8 scripts | Built, tested offline |
| Stages 5/7/8 real media | Not yet — needs RSC download or existing clips |
| EdBot T1 triage tools | Prompt written, not built |
| ArtBot scaffold | Not scaffolded |
| JP01 sync | Behind AT01 — needs git pull upstream main (32b179c vs 44f7d02) |
| raptor-history media | No footage imported yet |
| YD machine | Pre-meeting setup in progress |
| YD repo access | Not yet granted (only xriel84 + NewEccentric on AL/edbot) |
| RSC media on AT | Not downloaded (35.2 GB free) |
| Resolve | Running (PID 15288) |

## Blockers

| Blocker | Owner | Impact |
|---------|-------|--------|
| YD not added to AgileLens/edbot | Alex/Sam | Blocks YD clone + smoke test |
| raptor-history footage not imported | AT | Blocks JP track entirely |
| ArtBot not scaffolded | AT | Blocks image pipeline |

## Next Session Priorities

### AT Track (AgileLens)
1. Confirm YD access granted -> send her clone command
2. Build EdBot T1 triage + ArtBot scaffold
3. Download RSC media -> smoke test Stages 5/7/8
4. Use Resolve (already running) for Stage 6

### JP Track (raptor-history)
1. git pull upstream main on JP01 to get Stages 5/7/8
2. Create C:\NB11\media\raptor-history\
3. Import personal portfolio footage
4. Run triage + pipeline on raptor-history clips (after T1 tools built on AT)

### Shared
- Any EdBot tool improvements: commit on AT01 first, JP pulls from upstream
- Resolve projects: prefix EDBOT_ for AgileLens, RH_ for raptor-history, never mix
