---
name: nodejs-asset-bridge
description: Node.js integration for asset management and review server. al_asset_bridge.js (1235 lines), al_review_server.js (545 lines, port 3456), al_gen.js. JSON message bus IPC via agents/shared/*.json. Triggers on asset pipeline, review gallery, Node.js tools, Python-Node.js integration, message bus.
---

# Node.js Asset Bridge

## Tools
- `al_asset_bridge.js`: scan → sort → map → review → place → generate (1235 lines)
- `al_review_server.js`: web gallery on :3456 (545 lines)
- `al_gen.js`: batch-submit workflows to ComfyUI API

## IPC Protocol (Python ↔ Node.js)
- Transport: JSON files in `agents/shared/*.json`
- Schema: `{id, from, to, type, timestamp, subject, body, data, status}`
- Types: FEEDBACK, REQUEST, REPORT
- Status flow: unread → read → actioned
- Python writes: `json.dump()` with `indent=2`
- JS reads: `JSON.parse(fs.readFileSync())`

## Error Handling
All cross-language errors include:
`{source: "nodejs", error_type: "category", message: "human-readable", context: {}}`
