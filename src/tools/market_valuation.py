"""Valuation multiples, computed from a quoted price and filing figures.

This module exists because a valuation multiple is structurally different
from every other number in this project. A margin or a coverage ratio is
computable from a 10-K alone; a P/E is not, because half of it is what the
market is charging today. There is no filing-only path to one — so rather
than leave every non-corpus ticker permanently null on valuation, this
module computes the multiples explicitly and labels where each half came
from.

The boundary it respects: ``metrics_engine.compute_ratios`` stays
filing-only and a price never enters it. Anything here is market-derived,
carries the price and the timestamp it was computed at, and must be
reported that way in a research note — "P/E 47.2x at $184.20 as of
2026-08-03", never a bare figure presented like a filing fact. A multiple
computed from a price is stale the moment the market moves, which a margin
from a 10-K is not.

The arithmetic itself is as deterministic as the rest of the project:
inputs in, division out, ``None`` (with a stated reason) whenever an input
is missing or the multiple would be meaningless.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from src.tools.edgar_fundamentals import fetch_live_fundamentals
from src.tools.quotes import get_quote


def _safe_div(numerator: float | None, denominator: float | None) -> float | None:
    """Divide two numbers, returning None instead of raising or guessing."""
    if numerator is None or denominator is None or denominator == 0:
        return None
    return numerator / denominator


def compute_market_valuation(ticker: str) -> dict[str, Any]:
    """Return market-derived valuation multiples for a ticker.

    Combines one quoted price with the latest annual filing figures. Every
    multiple is either a number with its inputs shown, or None with a reason
    in ``unavailable`` — never an estimate.
    """
    quote = get_quote(ticker)
    if "error" in quote:
        return {"ticker": ticker.upper(), "error": quote["error"]}

    price = quote.get("price")
    if price is None:
        return {"ticker": ticker.upper(), "error": "No price returned for this ticker."}

    fundamentals = fetch_live_fundamentals(ticker)

    eps = fundamentals.get("eps")
    shares = fundamentals.get("shares_outstanding")
    ebitda = fundamentals.get("ebitda")
    total_debt = fundamentals.get("total_debt")
    cash = fundamentals.get("cash_and_equivalents")

    unavailable: dict[str, str] = {}

    market_cap = price * shares if shares is not None else None
    if market_cap is None:
        unavailable["market_cap"] = "The filer doesn't tag a share count this module can read."

    # A P/E only needs price and EPS — no share count involved, so it often
    # resolves even when market cap doesn't.
    pe_ratio = None
    if eps is None:
        unavailable["pe_ratio"] = "No diluted EPS reported for the latest annual period."
    elif eps <= 0:
        unavailable["pe_ratio"] = f"Diluted EPS is {eps}; a P/E multiple isn't meaningful at or below zero."
    else:
        pe_ratio = price / eps

    net_debt = total_debt - cash if total_debt is not None and cash is not None else None
    enterprise_value = market_cap + net_debt if market_cap is not None and net_debt is not None else None

    ev_to_ebitda = _safe_div(enterprise_value, ebitda)
    if ev_to_ebitda is None and "ev_to_ebitda" not in unavailable:
        if ebitda is None:
            unavailable["ev_to_ebitda"] = "EBITDA is unavailable — the filer doesn't tag a D&A line."
        elif enterprise_value is None:
            unavailable["ev_to_ebitda"] = "Enterprise value needs both a market cap and a net debt figure."

    return {
        "ticker": ticker.upper(),
        "company": fundamentals.get("company"),
        "as_of": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "price": price,
        "basis": (
            "Market-derived: a quoted price combined with the latest annual filing figures. "
            "Report these with the price and as-of time, not as filing facts — they move with "
            "the market."
        ),
        "valuation": {
            "market_cap": market_cap,
            "pe_ratio": pe_ratio,
            "enterprise_value": enterprise_value,
            "ev_to_ebitda": ev_to_ebitda,
        },
        "unavailable": unavailable,
        "inputs_used": {
            "price": price,
            "price_source": "live quote (Yahoo Finance via yfinance)",
            "eps": eps,
            "shares_outstanding": shares,
            "ebitda": ebitda,
            "depreciation_amortization": fundamentals.get("depreciation_amortization"),
            "operating_income": fundamentals.get("operating_income"),
            "total_debt": total_debt,
            "cash_and_equivalents": cash,
            "net_debt": net_debt,
            "fiscal_year": fundamentals.get("fiscal_year"),
            "filing_source": fundamentals.get("source"),
        },
    }
