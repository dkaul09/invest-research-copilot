"""Personal watchlist: a list of tickers you're tracking, not a trade.

This is deliberately the one piece of state in the project that's mutable
from the outside — adding or removing a ticker from a personal watchlist
isn't placing, modifying, or canceling a trade, so the read-only boundary
that applies to account/brokerage data doesn't apply here. It's closer to a
to-do list than a financial transaction.

Stored separately from data/portfolio/mock_account.json (which stays a pure
mock fixture) so the watchlist survives independent of any future swap to a
live account adapter.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

DEFAULT_WATCHLIST_PATH = Path(__file__).resolve().parents[2] / "data" / "portfolio" / "watchlist.json"

_SEED_WATCHLIST = [
    {"ticker": "AMD", "sector": "Technology"},
    {"ticker": "COST", "sector": "Consumer Staples"},
    {"ticker": "DIS", "sector": "Communication Services"},
]


def _load(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(_SEED_WATCHLIST, f, indent=2)
        return list(_SEED_WATCHLIST)
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _save(path: Path, items: list[dict[str, Any]]) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(items, f, indent=2)


def get_watchlist(path: Path = DEFAULT_WATCHLIST_PATH) -> list[dict[str, Any]]:
    return _load(path)


def add_to_watchlist(ticker: str, sector: str = "", path: Path = DEFAULT_WATCHLIST_PATH) -> list[dict[str, Any]]:
    items = _load(path)
    ticker = ticker.upper()
    if any(item["ticker"] == ticker for item in items):
        return items
    items.append({"ticker": ticker, "sector": sector or "Unknown"})
    _save(path, items)
    return items


def remove_from_watchlist(ticker: str, path: Path = DEFAULT_WATCHLIST_PATH) -> list[dict[str, Any]]:
    items = _load(path)
    ticker = ticker.upper()
    items = [item for item in items if item["ticker"] != ticker]
    _save(path, items)
    return items
