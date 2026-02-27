---
name: at01-comms
description: Write AT01↔JP01 inter-repo communication files, Slack messages for Sam/YD, and comms log entries. Use this skill whenever the user asks to write a comms file, respond to JP, message Sam, update the comms log, write a handoff message, or coordinate between AT01 and JP01 repos. Also trigger on "write to JP", "respond to comms", "check inbox", "comms before push", or any cross-repo coordination task. CRITICAL for privacy boundary enforcement — always use this before any cross-repo output.
---

# AT01 Comms Protocol

## Purpose
Enforces communication formats and privacy boundaries across AT01↔JP01, AT01↔YD (AgileLens/edbot), and AT01↔Sam (Slack only).

## Privacy Matrix — MEMORIZE THIS

| Actor | AT01 (public) | JP01 (private) | Channel |
|-------|---------------|----------------|---------|
| Ari (xriel84) | OWNER | READ for coordination | Git, Claude Code (/rielt) |
| JP (NewEccentric) | READ via fork | OWNER | Git, Claude Code (/stran) |
| Sam | Slack ONLY | **ZERO ACCESS. EVER.** | Slack public channels |
| YD | Worktree branches | No access | Claude Code (/rielt) |

## Message Formats

### AT↔JP Private Comms (comms/private/)

**Location:** `C:\AT01\comms\private\`
**NEVER committed. NEVER pushed. LOCAL ONLY.**

```
comms/private/
  ├── at-to-jp/    ← AT writes here
  ├── jp-to-at/    ← JP writes here (AT copies from C:\JP01\comms\at\)
  └── comms-log.md ← Index of all messages
```

**Filename:** `{YYYY-MM-DD}T{HH-MM}-at-{slug}.md` (AT outbound)
**Filename:** `{YYYY-MM-DD}T-{slug}.md` (JP inbound, copied as-is)

**Template:**
```markdown
# COMMS: AT01 → JP01
# Type: RESPONSE | HANDOFF | STATUS | BLOCKER | QUESTION
# Date: {YYYY-MM-DD}
# Re: {original message filename if responding}

---

## {SECTION TITLE}
{content}
```

### AT↔YD Comms (AgileLens/edbot repo)

**Each actor commits only to their own branch. No overwrites.**

| Direction | Writer writes to | On branch | Reader pulls to read |
|-----------|-----------------|-----------|---------------------|
| AT→YD | comms/from-at/ | at | YD pulls `at` |
| YD→AT | comms/from-yd/ | AL | AT pulls `AL` |

**Filename:** `{YYYY-MM-DD}T-{topic}.md`
**Commit prefix:** `[aribot]` on at branch, `[yd]` on AL branch

### AT↔Sam (Slack ONLY)

Sam interacts via Slack public channels only. Content rules:
- NEVER mention JP01, NewEccentric, C:\JP01, or any jp_ prefixed content
- NEVER share comms/private/ contents
- NEVER reference personal credentials or OAuth tokens
- Safe topics: AT01 tools, test counts, endpoint status, AgileLens/edbot coordination

## Comms Log Format

File: `C:\AT01\comms\private\comms-log.md`

```markdown
# AT01 ↔ JP01 Comms Log

| Date | Direction | File | Topic | Status |
|------|-----------|------|-------|--------|
| {date} | JP→AT | {filename} | {topic} | RECEIVED |
| {date} | AT→JP | {filename} | {topic} | SENT |
```

## Pre-Push Checklist

Before ANY git push from AT01:
1. ✅ No C:\JP01 paths in staged files
2. ✅ No NewEccentric references in staged files
3. ✅ No jp_ prefixed content in AT01 code files
4. ✅ No credential paths (token.json, OAuth)
5. ✅ comms/private/ is in .gitignore
6. ✅ Comms file written for any cross-repo coordination

## Reading JP Inbox

```powershell
# Check for new JP messages
Get-ChildItem C:\JP01\comms\at\ -Filter *.md 2>$null | Sort-Object Name
# Copy to AT inbox
Copy-Item "C:\JP01\comms\at\{filename}" "C:\AT01\comms\private\jp-to-at\{filename}"
```

## Message Bus (Runtime Agent↔Agent)

Location: `C:\AT01\agents\shared\`

```json
{
  "messages": [{
    "id": "msg_{NNN}",
    "from": "anabot|edbot|artbot|codebot|jasperbot",
    "to": "target_agent",
    "type": "FEEDBACK|REQUEST|REPORT",
    "timestamp": "ISO-8601",
    "subject": "string",
    "body": "string",
    "data": {},
    "status": "unread|read|actioned"
  }]
}
```

Cross-repo bus files (AT01↔JP01):
- jasperbot-to-artbot.json / artbot-to-jasperbot.json
- jasperbot-to-anabot.json / anabot-to-jasperbot.json
