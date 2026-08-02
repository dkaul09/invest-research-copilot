#!/usr/bin/env python3
"""PreToolUse hook: hard-deny any tool call that looks like order execution.

This is the primary safety boundary against the assistant ever placing a
trade. It fires on EVERY tool call (Bash, any MCP tool, anything future),
and denies if the tool name or its serialized arguments match a pattern
associated with trade execution. Fail-closed: matching means deny, no
exceptions, no confirmation prompt to bypass.

Claude Code PreToolUse hook protocol: reads a JSON payload from stdin with
at least {"tool_name": ..., "tool_input": {...}}. Emitting
{"hookSpecificOutput": {"permissionDecision": "deny", ...}} on stdout with
exit code 0 blocks the tool call and surfaces the reason to the assistant.
"""

import json
import re
import sys

# Deliberately broad: false positives (a benign call that happens to mention
# "order") are an acceptable cost given the alternative is a missed trade
# execution path. Word-boundary matching keeps this from over-triggering on
# unrelated substrings like "coordinate" or "buyer_persona_doc".
BANNED_PATTERN = re.compile(
    r"\b(trade|order|buy|sell|cancel_order|submit_order|execute_order|place_order|liquidate)\b",
    re.IGNORECASE,
)


def main() -> None:
    payload = json.load(sys.stdin)
    tool_name = payload.get("tool_name", "")
    tool_input = payload.get("tool_input", {})

    haystack = tool_name + " " + json.dumps(tool_input)
    match = BANNED_PATTERN.search(haystack)

    if match:
        decision = {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": (
                    f"Blocked: tool call matched trade-execution pattern '{match.group(0)}'. "
                    "This project is a read-only research copilot and must never place, "
                    "modify, or cancel a trade. If this is a false positive on a research "
                    "question (e.g. 'why did the company sell a division'), rephrase the "
                    "tool call to avoid the flagged term, or ask the question directly "
                    "instead of via a tool call."
                ),
            }
        }
        print(json.dumps(decision))
        sys.exit(0)

    # No match: allow silently by producing no output.
    sys.exit(0)


if __name__ == "__main__":
    main()
