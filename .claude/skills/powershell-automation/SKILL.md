---
name: powershell-automation
description: PowerShell automation for Windows 11 system tasks on ENKI64. File operations, service management, SMB shares, process control, git operations, environment variables. Triggers on PowerShell scripts, Windows services, firewall, SMB, file management, system automation. No CMD, no Unix syntax.
---

# PowerShell Automation

## RULES
- PowerShell ONLY — never CMD, never bash syntax
- `py -3.12` — never bare `python`
- Path separator: backslash in PS, forward slash in Python

## Common Operations
```powershell
# Services
Get-Service {name} | Select Status

# Process management
Stop-Process -Name "ollama*" -Force

# File operations
Test-Path {path}; Copy-Item {src} {dst}; Move-Item {src} {dst}

# Network diagnostics
Test-NetConnection -ComputerName {ip} -Port {port}

# SMB shares
Get-SmbShare | Format-Table Name,Path

# Environment variables (user level)
[System.Environment]::GetEnvironmentVariable("VAR","User")
[System.Environment]::SetEnvironmentVariable("VAR","value","User")

# Git
gh auth status; git pull origin main; git push origin main
```

## Machine: ENKI64
- IP: 192.168.1.115 | RTX A6000 48GB | 128GB RAM | Win11
- AT01: C:\AT01 | JP01: C:\JP01
- Ollama: 0.0.0.0:11434 | Resolve: Studio 20.3.1.6 | ComfyUI: :8188
