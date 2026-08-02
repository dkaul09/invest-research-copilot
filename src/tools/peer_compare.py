"""Build a side-by-side metric comparison table for a ticker and its peers.

Delegates all number-crunching to ``metrics_engine.compute_ratios`` — this
module only assembles fundamentals for the requested tickers and shapes the
result into a table. It never computes a ratio itself and never fabricates a
peer's numbers when they aren't present in the local filing corpus (missing
peers are reported as such, not silently dropped or guessed).
"""

from __future__ import annotations

from typing import Any

from src.tools.fundamentals import get_fundamentals
from src.tools.metrics_engine import compute_ratios


def compare_peers(ticker: str, peers: list[str]) -> dict[str, Any]:
    """Return a metrics table for ``ticker`` and each of ``peers``.

    Any ticker not present in the local filing corpus is listed under
    ``missing`` rather than silently omitted, so the caller knows the
    comparison is incomplete instead of assuming full coverage.
    """
    all_tickers = [ticker] + list(peers)
    rows: dict[str, Any] = {}
    missing: list[str] = []

    for t in all_tickers:
        fundamentals = get_fundamentals(t)
        if fundamentals is None:
            missing.append(t)
            continue
        computed = compute_ratios(fundamentals)
        rows[t] = {
            "company": fundamentals.get("company", t),
            "fiscal_year": fundamentals.get("fiscal_year"),
            "ratios": computed["ratios"],
        }

    return {
        "primary": ticker,
        "peers": peers,
        "table": rows,
        "missing": missing,
    }
