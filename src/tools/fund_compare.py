"""Side-by-side comparison of funds with the same or a similar mandate.

"Is VOO or IVV the better S&P 500 fund?" is the question index-fund
investors actually ask, and it is answered by a small number of comparable
facts — cost, scale, turnover, concentration — not by a view on the
underlying market. This module lays those out and stops there.

It builds on ``fund_profile``, so every figure it reports is vendor-sourced
and stamped as such. That is a deliberate limit: comparing four funds
against their prospectuses would mean fetching a dozen multi-megabyte
documents, so the comparison table is the fast vendor pass, and the memo is
expected to confirm the deciding figure — usually the expense ratio —
against the prospectus via ``search_fund_filings``.

Tickers that aren't supported funds appear in ``unavailable`` with the
registry's reason. They are never dropped silently and never filled in from
memory: a comparison table missing a row is obvious, whereas a table with a
fabricated row is not.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from src.tools.fund_profile import get_fund_profile

# The fields that actually differentiate two funds tracking one index.
_COMPARISON_FIELDS = (
    ("name", ("identity", "name")),
    ("category", ("identity", "category")),
    ("family", ("identity", "family")),
    ("expense_ratio", ("costs_and_scale", "expense_ratio")),
    ("total_net_assets", ("costs_and_scale", "total_net_assets")),
    ("holdings_turnover", ("costs_and_scale", "holdings_turnover")),
    ("top_10_weight", ("exposure", "top_10_weight")),
)


def _extract(profile: dict[str, Any], path: tuple[str, str]) -> Any:
    section, field = path
    return profile.get(section, {}).get(field, {}).get("value")


def compare_funds(tickers: list[str]) -> dict[str, Any]:
    """Build a comparison table across funds. Unsupported tickers are listed, not guessed."""
    as_of = datetime.now(timezone.utc).isoformat(timespec="seconds")

    rows: list[dict[str, Any]] = []
    unavailable: list[dict[str, Any]] = []
    for ticker in tickers:
        profile = get_fund_profile(ticker)
        if profile.get("status") != "ok":
            unavailable.append(
                {
                    "ticker": ticker.upper(),
                    "status": profile.get("status"),
                    "reason": profile.get("reason"),
                }
            )
            continue
        rows.append(
            {
                "ticker": profile["ticker"],
                **{name: _extract(profile, path) for name, path in _COMPARISON_FIELDS},
            }
        )

    # Funds tracking one index often charge exactly the same fee (VOO and
    # IVV are both 0.03%). Returning a single "cheapest" would manufacture a
    # difference that doesn't exist, so ties are reported as ties.
    cheapest: list[str] = []
    priced = [r for r in rows if r.get("expense_ratio") is not None]
    if priced:
        lowest = min(r["expense_ratio"] for r in priced)
        cheapest = [r["ticker"] for r in priced if r["expense_ratio"] == lowest]

    return {
        "status": "ok",
        "as_of": as_of,
        "source": "vendor",
        "basis": (
            "Vendor-sourced (Yahoo Finance via yfinance) for speed across several funds. "
            "Confirm the deciding figure — normally the expense ratio — against the prospectus "
            "with search_fund_filings before relying on it."
        ),
        "funds": rows,
        "unavailable": unavailable,
        "lowest_expense_ratio_tickers": cheapest,
        "note": (
            "Total net assets are reported in millions by the vendor feed. Expense ratio and "
            "turnover are fractions, not percentages. When lowest_expense_ratio_tickers holds "
            "more than one ticker the funds charge the same fee — say so rather than picking one."
        ),
    }
