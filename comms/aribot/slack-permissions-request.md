# Slack Permissions Request — AriBot
Date: 2026-02-25
To: Sam (clawdbot) via Agile Lens Slack
Status: DRAFT — Ari to review and send manually

---

Hey Sam — I'm setting up AriBot as a local agent that can read and post
to our public Slack channels. I need permission to create a Slack App in
our workspace with these bot token scopes:

  - channels:history (read public channel messages)
  - channels:read (list channels)
  - chat:write (post messages)
  - users:read (get user profiles)

AriBot will only interact with public channels — no DMs, no admin access,
no private channels. All posts will be human-gated (I approve before
anything sends). Can you grant me app creation permissions, or create
the app and send me the bot token?

Also need the Team ID (visible in workspace URL after login:
app.slack.com/client/TXXXXXXX/...).
