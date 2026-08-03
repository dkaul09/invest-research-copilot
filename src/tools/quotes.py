"""Live price quotes and historical trend data.

Unlike the rest of this project, prices are inherently point-in-time facts
that must come from the market, not a filing — there's no deterministic
"correct" price to compute, only what the market last quoted. This module
draws that line honestly: everything it returns is a straight passthrough
of what yfinance (a wrapper around Yahoo Finance's public quote data)
reports, with no interpretation or estimation layered on top.

This is display/data infrastructure for the watchlist, not a research
input — the equity-research skill's hard rule ("never state a number that
wasn't produced by compute_metrics") is unaffected: a live price is a
price, not a financial ratio, and it's never used as an input to
compute_ratios.
"""

from __future__ import annotations

from typing import Any

import yfinance as yf


def get_quote(ticker: str) -> dict[str, Any]:
    """Return the latest price, prior close, and day change for a ticker."""
    t = yf.Ticker(ticker.upper())
    try:
        info = t.fast_info
        last_price = info.last_price
        prev_close = info.previous_close
    except Exception as exc:
        return {"ticker": ticker.upper(), "error": f"Could not fetch quote: {exc}"}

    if last_price is None:
        return {"ticker": ticker.upper(), "error": "No quote data returned for this ticker."}

    change = last_price - prev_close if prev_close else None
    change_pct = (change / prev_close) if change is not None and prev_close else None

    return {
        "ticker": ticker.upper(),
        "price": round(float(last_price), 2),
        "previous_close": round(float(prev_close), 2) if prev_close else None,
        "change": round(float(change), 2) if change is not None else None,
        "change_pct": round(float(change_pct), 4) if change_pct is not None else None,
    }


def get_price_history(ticker: str, period: str = "3mo") -> dict[str, Any]:
    """Return a list of {date, close} points for sparkline/trend rendering.

    period follows yfinance's convention: 1mo, 3mo, 6mo, 1y, 5y, max.
    """
    t = yf.Ticker(ticker.upper())
    try:
        hist = t.history(period=period)
    except Exception as exc:
        return {"ticker": ticker.upper(), "error": f"Could not fetch price history: {exc}", "points": []}

    if hist.empty:
        return {"ticker": ticker.upper(), "error": "No price history returned for this ticker.", "points": []}

    points = [
        {"date": ts.strftime("%Y-%m-%d"), "close": round(float(row["Close"]), 2)}
        for ts, row in hist.iterrows()
    ]
    return {"ticker": ticker.upper(), "period": period, "points": points}
