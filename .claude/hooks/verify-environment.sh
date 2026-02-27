#!/bin/bash
# Verify correct GitHub account
ACCOUNT=$(gh auth status 2>&1 | grep -o 'account [^ ]*' | head -1)
if ! echo "$ACCOUNT" | grep -q "xriel84"; then
  echo "⚠️ Wrong GitHub account. Run: gh auth switch --user xriel84" >&2
fi

# Check Resolve env vars
if [ -z "$RESOLVE_SCRIPT_API" ]; then
  echo "⚠️ RESOLVE_SCRIPT_API not set — Resolve bridge will fail" >&2
fi

# Check Python version
PY_VER=$(py -3.12 --version 2>&1)
if ! echo "$PY_VER" | grep -q "3.12"; then
  echo "⚠️ py -3.12 not responding correctly: $PY_VER" >&2
fi

exit 0
