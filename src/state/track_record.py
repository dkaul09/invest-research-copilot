"""Score previously stated views against what prices actually did.

This is the one thing a general research tool cannot do: it never took a
position, so it has nothing to be graded on. Because every note here states a
dated rating into an append-only ledger, those calls can be lined up against
outcomes afterward.

Scoring is deliberately crude, and honest about it — direction only, over a
minimum holding window, against a market price carrying its own as-of time. It
is a record of what was said and what happened next, not a performance claim,
and it says nothing about whether the reasoning was sound.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

# A "neutral" call is right when the price went roughly nowhere. The band is a
# judgement call, not a derived constant.
NEUTRAL_BAND_PCT = 5.0

VALID_RATINGS = {"bullish", "neutral", "bearish"}


def _parse_ts(raw: str) -> datetime:
    return datetime.fromisoformat(raw.replace("Z", "+00:00"))


def _status(rating: str, pct_change: float) -> str:
    if rating == "bullish":
        return "correct" if pct_change > 0 else "incorrect"
    if rating == "bearish":
        return "correct" if pct_change < 0 else "incorrect"
    return "correct" if abs(pct_change) <= NEUTRAL_BAND_PCT else "incorrect"


def score_views(
    views: list[dict[str, Any]],
    current_prices: dict[str, float],
    now: datetime,
    min_days: int = 7,
) -> dict[str, Any]:
    """Line up recorded views against current prices.

    A view younger than ``min_days``, or one whose ticker has no current
    price, is ``pending`` rather than graded — a call needs time before it can
    be judged, and a missing quote is not evidence of anything.
    """
    rows: list[dict[str, Any]] = []

    for run in views:
        view = run.get("view") or {}
        rating = view.get("rating")
        if rating not in VALID_RATINGS:
            continue

        timestamp = run.get("timestamp")
        if not timestamp:
            continue

        for ticker, view_price in (view.get("view_price") or {}).items():
            if not view_price:
                continue

            current = current_prices.get(ticker)
            mature = now - _parse_ts(timestamp) >= timedelta(days=min_days)

            if current is None or not mature:
                pct_change = None
                status = "pending"
            else:
                pct_change = round((current - view_price) / view_price * 100, 1)
                status = _status(rating, pct_change)

            rows.append(
                {
                    "run_id": run.get("run_id"),
                    "timestamp": timestamp,
                    "ticker": ticker,
                    "rating": rating,
                    "view_price": view_price,
                    "current_price": current,
                    "pct_change": pct_change,
                    "status": status,
                    "note_path": run.get("note_path"),
                }
            )

    resolved = [r for r in rows if r["status"] != "pending"]
    return {
        "summary": {
            "total": len(rows),
            "resolved": len(resolved),
            "correct": sum(1 for r in resolved if r["status"] == "correct"),
        },
        "rows": rows,
    }
