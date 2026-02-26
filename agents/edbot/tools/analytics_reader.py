"""Read AnaBot recommendations from the agent message bus.

First live cross-agent communication tool in the EdBot pipeline. Reads
messages from the shared anabot-to-edbot.json bus file, filters by type
and read status, and can mark messages as read or actioned.

Bus schema defined in agents/shared/schema.md.
"""

import argparse
import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

VALID_TYPES = {"FEEDBACK", "REQUEST", "REPORT"}
VALID_STATUSES = {"read", "actioned"}
REQUIRED_FIELDS = {"id", "type", "status"}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _load_bus(bus_path: str) -> list[dict[str, Any]] | None:
    """Load messages from bus file. Returns list or None on failure."""
    path = Path(bus_path)
    if not path.exists():
        logger.warning("Bus file not found: %s", bus_path)
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("Failed to read bus file %s: %s", bus_path, exc)
        return None

    if not isinstance(data, dict) or "messages" not in data:
        logger.warning("Bus file missing 'messages' key: %s", bus_path)
        return None

    return data["messages"]


def _is_valid_message(msg: Any) -> bool:
    """Check that a message has the required fields with valid values."""
    if not isinstance(msg, dict):
        return False
    for field in REQUIRED_FIELDS:
        val = msg.get(field)
        if not isinstance(val, str) or not val:
            return False
    if msg["type"] not in VALID_TYPES:
        return False
    return True


# ---------------------------------------------------------------------------
# Core API
# ---------------------------------------------------------------------------


def read_messages(
    bus_path: str = "agents/shared/anabot-to-edbot.json",
    filter_type: str | None = None,
    unread_only: bool = True,
) -> list[dict[str, Any]]:
    """Read messages from AnaBot bus file.

    Args:
        bus_path: Path to the bus JSON file, relative to repo root or absolute.
        filter_type: One of "FEEDBACK", "REQUEST", "REPORT", or None for all.
        unread_only: If True, return only messages with status "unread".

    Returns:
        List of message dicts matching the filters. Empty list on any error.
    """
    if filter_type is not None and filter_type not in VALID_TYPES:
        return []

    raw = _load_bus(bus_path)
    if raw is None:
        return []

    results: list[dict[str, Any]] = []
    for msg in raw:
        if not _is_valid_message(msg):
            continue
        if filter_type is not None and msg.get("type") != filter_type:
            continue
        if unread_only and msg.get("status") != "unread":
            continue
        results.append(msg)

    return results


def mark_message(
    bus_path: str,
    message_id: str,
    new_status: str = "actioned",
) -> dict[str, Any]:
    """Update message status in the bus file.

    Args:
        bus_path: Path to the bus JSON file.
        message_id: The message ID to update.
        new_status: New status value, one of "read" or "actioned".

    Returns:
        The updated message dict on success, or an error dict on failure.
    """
    if new_status not in VALID_STATUSES:
        return {
            "status": "error",
            "error": f"invalid status: {new_status}",
            "code": "INVALID_INPUT",
        }

    path = Path(bus_path)
    if not path.exists():
        return {
            "status": "error",
            "error": f"bus file not found: {bus_path}",
            "code": "NOT_FOUND",
        }

    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError) as exc:
        return {
            "status": "error",
            "error": f"failed to read bus file: {exc}",
            "code": "READ_ERROR",
        }

    if not isinstance(data, dict) or "messages" not in data:
        return {
            "status": "error",
            "error": "bus file missing 'messages' key",
            "code": "READ_ERROR",
        }

    # Find the target message.
    for msg in data["messages"]:
        if isinstance(msg, dict) and msg.get("id") == message_id:
            msg["status"] = new_status
            # Write back.
            try:
                with open(path, "w", encoding="utf-8") as f:
                    json.dump(data, f, indent=2)
            except OSError as exc:
                return {
                    "status": "error",
                    "error": f"failed to write bus file: {exc}",
                    "code": "WRITE_ERROR",
                }
            return msg

    return {
        "status": "error",
        "error": f"message not found: {message_id}",
        "code": "NOT_FOUND",
    }


def apply_recommendations(
    bus_path: str = "agents/shared/anabot-to-edbot.json",
) -> dict[str, Any]:
    """Read unread FEEDBACK messages and extract actionable recommendations.

    Marks each processed message as 'read' and returns a summary of
    recommendations grouped by type.

    Returns dict with: applied (list of actioned items), skipped, errors, count.
    """
    messages = read_messages(bus_path, filter_type="FEEDBACK", unread_only=True)
    if not messages:
        return {"applied": [], "skipped": 0, "errors": 0, "count": 0}

    applied: list[dict[str, Any]] = []
    skipped = 0
    errors = 0

    for msg in messages:
        msg_id = msg.get("id", "")
        subject = msg.get("subject", "")
        body = msg.get("body", "")
        recommendation = msg.get("recommendation", body)

        if not recommendation:
            skipped += 1
            continue

        # Mark as read
        result = mark_message(bus_path, msg_id, "read")
        if result.get("code"):
            errors += 1
            continue

        applied.append({
            "id": msg_id,
            "subject": subject,
            "recommendation": recommendation,
            "status": "read",
        })

    return {
        "applied": applied,
        "skipped": skipped,
        "errors": errors,
        "count": len(applied),
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> None:
    """CLI entry point for analytics reader."""
    parser = argparse.ArgumentParser(
        description="Read AnaBot messages from the agent message bus",
    )
    parser.add_argument(
        "--bus-path", default="agents/shared/anabot-to-edbot.json",
        help="Path to bus JSON file (default: agents/shared/anabot-to-edbot.json)",
    )
    parser.add_argument(
        "--filter-type", default=None, choices=["FEEDBACK", "REQUEST", "REPORT"],
        help="Filter messages by type",
    )
    parser.add_argument(
        "--unread-only", action="store_true", default=True,
        help="Show only unread messages (default: True)",
    )
    parser.add_argument(
        "--all", action="store_true",
        help="Show all messages regardless of status",
    )
    parser.add_argument(
        "--mark", default=None,
        help="Message ID to mark (use with --mark-status)",
    )
    parser.add_argument(
        "--mark-status", default="actioned", choices=["read", "actioned"],
        help="Status to set when marking a message (default: actioned)",
    )
    parser.add_argument(
        "--json", action="store_true",
        help="Print output as JSON",
    )
    args = parser.parse_args()

    # Mark mode.
    if args.mark:
        result = mark_message(args.bus_path, args.mark, args.mark_status)
        if args.json:
            print(json.dumps(result, indent=2))
        else:
            if result.get("code"):
                print(f"  ERROR: {result['error']}")
            else:
                print(f"  Marked {result.get('id')} -> {result.get('status')}")
        return

    # Read mode.
    unread_only = not args.all
    messages = read_messages(args.bus_path, args.filter_type, unread_only)

    if args.json:
        print(json.dumps(messages, indent=2))
    else:
        if not messages:
            print("  No messages.")
            return
        for msg in messages:
            print(
                f"  [{msg.get('status', '?')}] {msg.get('id', '?')}: "
                f"{msg.get('type', '?')} — {msg.get('subject', '(no subject)')}"
            )


if __name__ == "__main__":
    main()
