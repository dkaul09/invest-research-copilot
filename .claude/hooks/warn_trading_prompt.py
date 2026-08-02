#!/usr/bin/env python3
"""UserPromptSubmit hook: warn (never block) on trade-adjacent language.

Unlike block_trading_tools.py, this hook never denies anything — a question
like "should I buy AAPL here" is a legitimate request for the assistant's
view, not a trade instruction, since this tool has no ability to execute
one regardless of how it answers. Blocking user prompts on keyword match
would make the tool unusable for exactly the questions it's meant to answer.

Instead, on a keyword hit this hook injects a reminder that the assistant
may give its view, grounded in the metrics/citations it gathers, but must
never claim a trade was actually placed or executed — because no tool in
this project can do that. The Stop hook (check_output_language.py) is the
actual enforcement point for that specific fabrication.
"""

import json
import re
import sys

TRIGGER_PATTERN = re.compile(
    r"\b(trade|order|buy|sell|should i buy|should i sell)\b",
    re.IGNORECASE,
)


def main() -> None:
    payload = json.load(sys.stdin)
    prompt = payload.get("prompt", "")

    if TRIGGER_PATTERN.search(prompt):
        output = {
            "hookSpecificOutput": {
                "hookEventName": "UserPromptSubmit",
                "additionalContext": (
                    "Reminder: you may state a view or rating (bullish/neutral/bearish, "
                    "buy/hold/sell) grounded in the metrics and citations gathered this turn "
                    "— that's allowed. What you must never do is claim a trade was actually "
                    "placed, executed, or filled ('I've placed this trade', 'your order was "
                    "filled'), and never call any tool that would place, modify, or cancel a "
                    "trade — no such tool exists in this project."
                ),
            }
        }
        print(json.dumps(output))

    sys.exit(0)


if __name__ == "__main__":
    main()
