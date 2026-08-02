#!/usr/bin/env python3
"""Stop hook: block the turn if the final assistant message uses advice language.

Scans the assistant's last message for banned recommendation phrasing
("you should buy", "sell immediately", "place this trade", "strong buy",
"I recommend buying", price-target-as-advice phrasing) and, on a match,
blocks the stop and instructs the assistant to rewrite using the approved
research vocabulary instead.

Claude Code's Stop hook payload includes a "transcript_path" pointing at the
session transcript (JSONL); this hook reads the last assistant message from
it. For unit testing, the hook also accepts a payload with a direct
"message" field so the language checker can be exercised without a full
transcript file.

Blocking protocol: emit {"decision": "block", "reason": ...} on stdout with
exit code 0 to make Claude Code continue the turn instead of stopping.
"""

import json
import re
import sys

BANNED_PATTERNS = [
    r"\byou should buy\b",
    r"\byou should sell\b",
    r"\bsell immediately\b",
    r"\bsell now\b",
    r"\bplace this trade\b",
    r"\bstrong buy\b",
    r"\bi recommend buying\b",
    r"\bi recommend selling\b",
    r"\bbuy now\b",
    r"\bthis is a buy\b",
]
BANNED_RE = re.compile("|".join(BANNED_PATTERNS), re.IGNORECASE)

APPROVED_VOCAB_REMINDER = (
    "Blocked: the response contains recommendation language, which this read-only "
    "research copilot must never produce. Rewrite the response using research "
    "framing instead — words like 'research note', 'risks', 'open questions', "
    "'watchlist candidate', and 'needs more evidence' — and remove any phrasing "
    "that tells the user to buy, sell, or place a trade."
)


def _last_assistant_text(transcript_path: str) -> str:
    text = ""
    with open(transcript_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if record.get("type") == "assistant":
                message = record.get("message", {})
                content = message.get("content", [])
                if isinstance(content, list):
                    text = "".join(
                        block.get("text", "") for block in content if isinstance(block, dict)
                    )
                elif isinstance(content, str):
                    text = content
    return text


def contains_banned_language(text: str) -> re.Match | None:
    return BANNED_RE.search(text)


def main() -> None:
    payload = json.load(sys.stdin)

    if "message" in payload:
        text = payload["message"]
    elif "transcript_path" in payload:
        try:
            text = _last_assistant_text(payload["transcript_path"])
        except (FileNotFoundError, OSError):
            text = ""
    else:
        text = ""

    match = contains_banned_language(text)
    if match:
        decision = {"decision": "block", "reason": APPROVED_VOCAB_REMINDER}
        print(json.dumps(decision))
        sys.exit(0)

    sys.exit(0)


if __name__ == "__main__":
    main()
