---
name: session-handoff
description: Generate AT01/JP01 session handoff documents, status updates, and mobile-pasteable Claude Code prompts. Use this skill whenever the user asks for a handoff, session summary, status doc, next-session prompt, or says "end of session", "wrap up", "handoff", "what's the state", or "generate prompt for next session". Also trigger when user mentions session numbers (S14, S15, etc.) in context of documenting or transitioning work.
---

# Session Handoff Generator

## Purpose
AT01/JP01 use structured handoff documents to maintain continuity across Claude Code sessions on /rielt and /stran. Every session ends with a handoff. This skill ensures consistent format, no missed state, and mobile-pasteable output.

## Handoff Document Format

### Filename Convention
`AT01-SESSION-STATUS-{YYYY-MM-DD}-post-s{N}.md`

### Required Sections (in order)

```markdown
# AT01 HANDOFF — {DATE} (Post Session {N})
## STATE
- Repo: C:\AT01 | {branch} | {commit_sha} | {test_count} tests | {tool_count} tools | {endpoint_count} endpoints
- Resolve Studio {version}: {status}
- Server: FastAPI :{port}
- Python 3.12.10 | PowerShell only | [aribot] commits | py -3.12

## SESSION {N} COMPLETED — {TITLE}
{bullet list of what was built/fixed/shipped}

## REPOS
| Repo | Branch | Commit | Remote |
|------|--------|--------|--------|
| AT01 | main | {sha} | origin/main |
| AgileLens/edbot | at | {sha} | agilelens/at |
| AgileLens/edbot | AL | — | YD working branch |
| JP01 | main | {sha} | NewEccentric/JP01 |

## BLOCKERS
{active blockers only — remove resolved ones}

## SESSION {N+1} CANDIDATES (ranked)
1. {highest priority}
2. ...

## CUMULATIVE SESSION LOG
| Session | Commit | Tests | Key Deliverables |
{append new row, keep all previous rows}

## KEY RULES
- py -3.12 (not python) | PowerShell only | [aribot] commits
- JP01 is PRIVATE, Sam has ZERO access, comms/private/ is AT↔JP only
- al_ prefix = AT01 | jp_ prefix = JP01 | never cross
- comms/private/ is LOCAL ONLY — never committed, never pushed
- AT can READ C:\JP01 for coordination, must NEVER leak private content to public
```

### Mobile Code Block (end of every handoff)

Always include a fenced code block labeled `# HANDOFF FOR NEXT CHAT` containing:
- Single-line state summary (repo, branch, commit, tests, tools, endpoints, port)
- Key infra state (Resolve version, ComfyUI version+path, VRAM)
- Shell constraints (py -3.12, PowerShell, commit prefix, GitHub account)
- What was completed this session (1-2 lines)
- What's queued next
- Active blockers
- Privacy reminder (JP01 PRIVATE, Sam ZERO access, prefix rules)
- Decision prompt: "Tell me which track and I'll plan the Claude Code prompt."

### Claude Code Prompt Format

When generating a next-session prompt:

```markdown
# AT01 SESSION {N} — CLAUDE CODE PROMPT
# Name: {kebab-case-descriptor}
# Summary: {one line}
# Owner: AT01 (xriel84) on /rielt
# Machine: ENKI64 (Windows 11, RTX A6000 48GB, 128GB RAM)
# Date: {YYYY-MM-DD}
# Prereqs: {previous session state}

## CONTEXT
{code block with current state}

## HARD RULES
{numbered list — always include: py -3.12, PowerShell only, [aribot] commits, test count preservation}

## PHASE 1 — {name}
### 1.1 {step}
{powershell commands}

## DO NOT
{explicit exclusion list}

## SUCCESS CRITERIA
{checkbox list}
```

## State Variables to Track

Always capture and carry forward:
- Test count (exact number — discrepancies must be noted)
- Commit SHA (short hash)
- Tool count and endpoint count
- Which remotes were pushed to
- Blocker status changes
- Comms sent/received this session

## Privacy Checks Before Output

Before finalizing any handoff:
1. No C:\JP01 paths in public-facing sections
2. No NewEccentric references in public materials
3. No credential paths or OAuth tokens
4. No jp_ content in AT01 sections
5. comms/private/ references marked LOCAL ONLY
