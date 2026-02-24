# Agent Message Bus Schema

## Overview

AnaBot (agent 15) and EdBot (agent 3) communicate via shared JSON files.
Each agent owns one outbox file. The other agent reads it as their inbox.

## Files

| File | Writer | Reader | Purpose |
|------|--------|--------|---------|
| `anabot-to-edbot.json` | AnaBot | EdBot | Analytics feedback, editing recommendations |
| `edbot-to-anabot.json` | EdBot | AnaBot | Performance data requests, A/B test results |

## Message Schema

```json
{
  "messages": [
    {
      "id": "msg_001",
      "from": "anabot | edbot",
      "to": "edbot | anabot",
      "type": "FEEDBACK | REQUEST | REPORT",
      "timestamp": "2026-02-24T14:30:00Z",
      "subject": "Short description",
      "body": "Full message text. Markdown allowed.",
      "data": {},
      "status": "unread | read | actioned"
    }
  ]
}
```

## Fields

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| id | string | yes | Unique message ID: `msg_{NNN}` auto-incrementing |
| from | string | yes | Sender agent: `anabot` or `edbot` |
| to | string | yes | Recipient agent: `anabot` or `edbot` |
| type | string | yes | FEEDBACK (insights), REQUEST (data query), REPORT (scheduled) |
| timestamp | string | yes | ISO 8601 UTC |
| subject | string | yes | One-line summary |
| body | string | yes | Full message, markdown allowed |
| data | object | no | Structured data (metrics, comparisons, configs) |
| status | string | yes | unread -> read -> actioned |

## Message Types

### FEEDBACK (AnaBot -> EdBot)
Analytics-driven editing recommendations:
- "Videos under 60s with text hooks get 3x engagement on TikTok"
- "Retention drops at 0:45 -- consider shorter cuts"
- "Vertical 9:16 outperforms 16:9 by 2x on IG Reels"

### REQUEST (EdBot -> AnaBot)
Data queries from the editing pipeline:
- "Need performance data for last 10 videos"
- "Which thumbnail style gets higher CTR?"
- "Compare engagement: talking-head vs. b-roll heavy"

### REPORT (either direction)
Scheduled or ad-hoc summaries:
- Weekly analytics digest
- Render completion with specs
- A/B test results

## Rules

1. Never delete messages. Append only.
2. Only the recipient changes `status` (unread -> read -> actioned).
3. The `data` field carries structured payloads -- keep `body` human-readable.
4. Message IDs are sequential per file. Check last ID before appending.
5. Always validate JSON after write. Corrupt bus = broken pipeline.

## Example: AnaBot Feedback

```json
{
  "id": "msg_001",
  "from": "anabot",
  "to": "edbot",
  "type": "FEEDBACK",
  "timestamp": "2026-02-24T14:30:00Z",
  "subject": "TikTok engagement: short clips win",
  "body": "Analysis of last 20 TikTok posts shows videos under 60s with text hooks in first 3s get 3x the engagement rate of longer content. Recommend: target 45-55s for TikTok cuts.",
  "data": {
    "platform": "tiktok",
    "sample_size": 20,
    "metric": "engagement_rate",
    "short_avg": 8.2,
    "long_avg": 2.7,
    "recommended_duration_s": [45, 55]
  },
  "status": "unread"
}
```
