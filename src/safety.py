"""Single source of truth for the banned recommendation-language check.

Used by the Stop hook (.claude/hooks/check_output_language.py) for Claude
Code sessions, by evals/graders.py for the eval scorecard, and by
backend/app.py for the web/Telegram frontends — every interface enforces
the same rule with the same patterns.
"""

from __future__ import annotations

import re

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


def contains_banned_language(text: str) -> re.Match | None:
    return BANNED_RE.search(text)
