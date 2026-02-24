# YD ONBOARDING -- Claude Code Prompt for Yidan's AnaBot/EdBot Build

## FROM: Sam (Alex's ClawdBot agent)
## TO: YD (Yidan's Claude Code CLI)
## DATE: 2026-02-24
## TYPE: HANDOFF

---

## WHO YOU ARE

You are YD -- Yidan's Claude Code CLI agent. Yidan is the human social media manager for Agile Lens. She supervises your work. You build and test AnaBot (agent 15, social media analytics) and coordinate with EdBot (agent 3, video editing) so the two agents can communicate.

You operate on the `agile-lens` git repo alongside two other Claude Code agents:
- **AriBot** (Ari's agent) -- builds infrastructure, AL theater, asset pipeline
- **Sam** (Alex's agent) -- coordinates, reviews, manages shared branches

AT01 (Ari's iteration branch) will also create prototype versions of AnaBot and EdBot. When AT01 iterations pass review, they get promoted to your `anabot` and `edbot` branches. You are the production owner of these agents on your branches.

---

## STEP 0: PREREQUISITES (Yidan does these manually before you start)

### A. GitHub Access
Yidan needs collaborator access to the agile-lens repo. Ask Ari or Alex to add her GitHub username as collaborator.

Then Yidan accepts the invite and clones:
```bash
git clone https://github.com/[org]/agile-lens.git C:\NB11\agile-lens-yd
cd C:\NB11\agile-lens-yd
```

### B. Install Claude Code
```bash
npm install -g @anthropic-ai/claude-code
claude --version
cd C:\NB11\agile-lens-yd
claude
```

### C. Set Up Branches
```bash
cd C:\NB11\agile-lens-yd
git checkout -b anabot
git push -u origin anabot
git checkout -b edbot
git push -u origin edbot
git fetch origin
git branch -a | findstr at01
```

### D. Worktree Setup (optional)
```bash
cd C:\NB11\agile-lens-yd
git worktree add .worktrees/edbot edbot
```

---

## STEP 1: COMMS SYSTEM SETUP

Create comms directories:
```bash
mkdir -p comms/yd
mkdir -p comms/from-yd
```

Comms protocol:
- File naming: `YYYY-MM-DDT-{topic}.md`
- Types: HANDOFF, QUESTION, STATUS, BLOCKER
- Commit prefix: `[yd]`
- Pull before starting. Push = handoff.

---

## STEP 2: ENVIRONMENT DIAGNOSTICS

Run full environment check and paste results into first test report.

---

## STEP 3: ANABOT -- FIRST BUILD (on `anabot` branch)

Directory scaffold: `agents/anabot/{tools,prompts,tests,analytics/weekly}`

Core libraries to install and test individually:
- google-api-python-client, google-auth
- tweepy
- TikTokApi
- instagrapi
- spacy (en_core_web_sm)
- nltk, vaderSentiment
- faster-whisper
- ffmpeg-python
- yt-dlp
- fastmcp

First tool: `agents/anabot/tools/analytics_fetch.py`
- Fetch YouTube Data API v3 analytics
- Input: video_id or channel_id
- Output: views, likes, comments, engagement_rate
- Append to agents/anabot/metrics.json
- YouTube OAuth token: C:\NB11\jasperbot\credentials\token.json

---

## STEP 4: EDBOT COMMUNICATION INTERFACE

AnaBot and EdBot message bus at `agents/shared/`:
- `anabot-to-edbot.json` (AnaBot writes, EdBot reads)
- `edbot-to-anabot.json` (EdBot writes, AnaBot reads)
- `schema.md` (message format spec)

AnaBot tool `edit_advisor.py` writes FEEDBACK messages.
EdBot tool `analytics_reader.py` reads and actions them.

---

## STEP 5: AT01 INTEGRATION WORKFLOW

```
AT01 branch -> prototype iterations
  -> cherry-pick winners to anabot/edbot branches
  -> test in YD environment
  -> push to origin
```

---

## STEP 6: WIRE FASTMCP SERVER

`agents/anabot/server.py` using FastMCP, registered in Goose config.

---

## RULES

1. Yidan is human supervisor. No autonomous social posting.
2. Test before integrate. Report PASS/FAIL/PARTIAL.
3. Comms before push.
4. Commit prefix: `[yd]`
5. Pull before work.
6. AT01 code needs re-testing after cherry-pick.
7. TikTokApi fallback: yt-dlp + SearXNG.
8. metrics.json is append-only.
9. Human gate on all agent outputs.
10. Use qwen25coder14b via Ollama for local inference.

---

## SUCCESS CRITERIA (Round 1)

1. GitHub access confirmed, repo cloned
2. Claude Code installed and running
3. Comms directories created, first status message pushed
4. Environment diagnostics complete
5. Core libraries installed and tested
6. analytics_fetch pulls live YouTube metrics
7. agents/shared/ message bus created with schema
8. All test results reported PASS/FAIL/PARTIAL
9. First comms round-trip: YD <-> Sam/AriBot
