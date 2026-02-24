# Getting Started with Claude Code CLI

## What is Claude Code?
Claude Code is a command-line AI assistant that can read, edit, and run
code in your project. You type instructions in plain English, it does
the work. Think of it as a coding partner that lives in your terminal.

## First Time Setup (one time only)

### Step 1: Open PowerShell
Press Win+X -> Terminal (or search "PowerShell" in Start menu)

### Step 2: Go to the project
```
cd C:\NB11\AT01
```

### Step 3: Launch Claude Code
```
claude
```
First time: browser opens for login. Use your Claude account.
After login, you'll see a `>` prompt -- that's Claude Code.

### Step 4: Test it works
Type this at the `>` prompt:
```
What files are in this directory?
```
Claude should list the project files. If it does, you're set.

Type `/quit` to exit.

## Daily Usage

### Starting a session
```
cd C:\NB11\AT01
claude
```

### Useful commands
- `/quit` -- exit Claude Code
- `/config` -- check your settings loaded
- `/plan` -- ask Claude to plan before doing

### Running tests
Instead of typing commands yourself, double-click:
- `tests\run_all_tests.ps1` -- runs all offline tests
- `tests\run_resolve_tests.ps1` -- runs Resolve tests (Resolve must be open)
- `tests\demos\demo_filename_match.ps1` -- see footage matching in action

### When something breaks
1. Copy the error message (select text, right-click to copy)
2. Paste it into Claude Code: "I got this error: [paste]"
3. Claude will explain what went wrong and how to fix it
4. If Claude can't fix it, paste the error into your Claude chat

### What NOT to do
- Don't run Python scripts by typing `python` -- always use `py -3.12`
- Don't delete files without asking Claude first
- Don't edit `.claude/settings.json` -- that's your safety config
- Don't run scripts in Resolve's install directory manually -- use the .ps1 wrappers
