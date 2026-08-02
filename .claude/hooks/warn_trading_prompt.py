#!/usr/bin/env python3
"""UserPromptSubmit hook: warn (never block) on trade-adjacent language.

Unlike block_trading_tools.py, this hook never denies anything — a question
like "why did Nike sell its Converse... wait, that's a different company" or
"should the assistant flag if a company plans to sell a division" is a
legitimate research question, not a trade instruction. Blocking user prompts
on keyword match would make the tool unusable for real research questions.

Instead, on a keyword hit this hook injects additional context reminding the
assistant that its output must stay in research framing regardless of how
the question was phrased. The Stop hook (check_output_language.py) is the
actual enforcement point for output language.
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
                    "Reminder: this is a read-only research copilot. Answer with research "
                    "framing only — research note, risks, open questions, watchlist "
                    "candidate, needs more evidence. Do not use recommendation language "
                    "like 'you should buy', 'sell immediately', or 'place this trade', and "
                    "do not call any tool that would place, modify, or cancel a trade."
                ),
            }
        }
        print(json.dumps(output))

    sys.exit(0)


if __name__ == "__main__":
    main()
