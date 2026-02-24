# AT01 — AriBot Context

## Identity
AriBot. GitHub: xriel84. Public repo for EdBot resolve-tools collaboration.

## Remotes
- `origin` = xriel84/AT01 (public)

## Shell
PowerShell only. No CMD. No Unix.
Use `py -3.12` — never bare `python`.

## Scope
- EdBot pipeline: Resolve automation (ingest, scope, timeline, deliver)
- Collaboration with Sam via AgileLens/edbot (at-test branch)
- YD onboarding via AT01 public repo

## Rules
- Pull before starting. Always.
- Commits prefixed with `[aribot]`
- Never read/write C:\NB10\
- Never reference JP01 in public comms or commits

## Preflight
Before ANY work, verify correct GitHub account:
```
gh auth switch --user xriel84
gh auth status
```
MUST show: `Logged in to github.com account xriel84`

## Private Comms (AT <-> JP)

Local-only channel. NEVER committed or pushed.

- Inbox (from JP): `comms/private/jp-to-at/`
- Outbox (to JP): `comms/private/at-to-jp/`
- Check inbox: `Get-ChildItem .\comms\private\jp-to-at\ -Filter *.md | Sort-Object Name`
- Read latest: `Get-ChildItem .\comms\private\jp-to-at\ -Filter *.md | Sort-Object Name | Select-Object -Last 1 | Get-Content`

### Writing a message
Filename: `{YYYY-MM-DD}T{HH-MM}-at-{slug}.md`
Always include YAML frontmatter (from, to, date, re).
Never edit or delete sent messages.

### Session start checklist
1. `gh auth status` — must show xriel84
2. Check inbox: `Get-ChildItem .\comms\private\jp-to-at\ -Filter *.md`
3. If new messages, read before starting work
