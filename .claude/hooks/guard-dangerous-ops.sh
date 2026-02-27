#!/bin/bash
HOOK_INPUT=$(cat)
CMD=$(echo "$HOOK_INPUT" | jq -r '.tool_input.command // ""')

# Block FFmpeg overwrite without explicit flag
if echo "$CMD" | grep -qE 'ffmpeg.*-y.*\.(mp4|mov|avi)$'; then
  echo "⚠️ FFmpeg overwrite without confirmation" >&2
  exit 2
fi

# Block git push to JP01 remotes from AT01 context
if echo "$CMD" | grep -qiE 'git push.*(neweccentric|JP01)'; then
  echo "⚠️ Blocked: pushing to JP01 from AT01 context" >&2
  exit 2
fi

# Block rm -rf on protected directories
if echo "$CMD" | grep -qE 'rm -rf.*(agents|comms|output|\.claude)'; then
  echo "⚠️ Blocked: recursive delete on protected directory" >&2
  exit 2
fi

# Block JP01 private paths in public-facing commands (git commit messages, echo to files)
if echo "$CMD" | grep -qE '(git commit|echo|Out-File).*C:\\JP01'; then
  echo "⚠️ Blocked: JP01 path in public-facing command" >&2
  exit 2
fi

exit 0
