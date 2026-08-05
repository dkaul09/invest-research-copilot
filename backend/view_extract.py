"""Second-pass extraction of the structured view from a finished note.

The agent loop returns prose. The track record needs a dated, machine-readable
rating. Rather than regexing the note — which silently yields nulls the moment
phrasing drifts — a small follow-up model call reads the finished note and
returns JSON. This mirrors how ``_enforce_safety`` already makes a second pass
over the final text.

Extraction never invents a price: ``view_price`` comes from quotes actually
observed during the run, so a recorded view price always traces back to a real
``get_quote`` call rather than to the model's recollection.
"""

from __future__ import annotations

import json
import re
from typing import Any

VALID_RATINGS = {"bullish", "neutral", "bearish"}

EXTRACT_PROMPT = """Read this research note and return ONLY a JSON object:

{"rating": "bullish" | "neutral" | "bearish" | null,
 "change_my_mind": ["<each falsifiable condition the note states>"]}

Use the note's stated View section. If the note states no view, use null.
Copy conditions verbatim from the note. Invent nothing.

NOTE:
"""


def tickers_from_tool_calls(tool_calls: list[dict[str, Any]]) -> list[str]:
    """Distinct uppercase tickers that appeared in recorded call arguments."""
    seen: list[str] = []
    for call in tool_calls:
        ticker = (call.get("args") or {}).get("ticker")
        if isinstance(ticker, str) and ticker.strip():
            upper = ticker.strip().upper()
            if upper not in seen:
                seen.append(upper)
    return seen


def parse_view_json(raw: str) -> dict[str, Any]:
    """Parse the extraction reply, defaulting to an empty view on anything odd."""
    empty: dict[str, Any] = {"rating": None, "change_my_mind": []}
    match = re.search(r"\{.*\}", raw, re.DOTALL)
    if not match:
        return empty
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError:
        return empty
    if not isinstance(data, dict):
        return empty

    rating = data.get("rating")
    if rating not in VALID_RATINGS:
        rating = None

    conditions = data.get("change_my_mind")
    if not isinstance(conditions, list):
        conditions = []
    conditions = [str(c).strip() for c in conditions if str(c).strip()]

    return {"rating": rating, "change_my_mind": conditions}


def extract_view(
    client: Any,
    note_text: str,
    tool_calls: list[dict[str, Any]],
    quotes: dict[str, float],
    model: str,
) -> dict[str, Any]:
    """Return the four-key view dict that ``SessionStore.finish_run`` accepts."""
    try:
        reply = client.messages.create(
            model=model,
            max_tokens=512,
            messages=[{"role": "user", "content": EXTRACT_PROMPT + note_text}],
        )
        raw = "".join(b.text for b in reply.content if b.type == "text")
        parsed = parse_view_json(raw)
    except Exception:
        # Extraction is best-effort metadata. A failure here must never break
        # the research answer the user actually asked for.
        parsed = {"rating": None, "change_my_mind": []}

    tickers = tickers_from_tool_calls(tool_calls)
    return {
        "rating": parsed["rating"],
        "tickers": tickers,
        "view_price": {t: quotes[t] for t in tickers if t in quotes},
        "change_my_mind": parsed["change_my_mind"],
    }
