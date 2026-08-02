"""Mock, read-only portfolio data source.

Loads a JSON fixture (``data/portfolio/mock_account.json``) through the
``PortfolioAdapter`` contract and derives per-holding market value, weight,
and unrealized P/L. This is the only account data source used by the MVP;
swapping in a live adapter later means only changing which class is
instantiated in ``load_default_adapter`` — nothing else in the system needs
to change.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from src.adapters.base import PortfolioAdapter

DEFAULT_ACCOUNT_PATH = Path(__file__).resolve().parents[2] / "data" / "portfolio" / "mock_account.json"


class MockPortfolioAdapter(PortfolioAdapter):
    """Reads a static JSON fixture. Read-only: no method here can write."""

    def __init__(self, account_path: Path = DEFAULT_ACCOUNT_PATH) -> None:
        self._account_path = account_path
        with open(account_path, "r", encoding="utf-8") as f:
            self._account: dict[str, Any] = json.load(f)

    def get_snapshot(self) -> dict[str, Any]:
        holdings = self._enrich_holdings(self._account["holdings"])
        total_market_value = sum(h["market_value"] for h in holdings)
        total_portfolio_value = total_market_value + self._account["cash"]

        for h in holdings:
            h["weight"] = h["market_value"] / total_portfolio_value if total_portfolio_value else None

        return {
            "account_id": self._account["account_id"],
            "as_of": self._account["as_of"],
            "cash": self._account["cash"],
            "holdings": holdings,
            "watchlist": self._account["watchlist"],
            "total_market_value": total_market_value,
            "total_portfolio_value": total_portfolio_value,
        }

    def get_holding(self, ticker: str) -> dict[str, Any] | None:
        for h in self._account["holdings"]:
            if h["ticker"] == ticker.upper():
                return self._enrich_holdings([h])[0]
        return None

    @staticmethod
    def _enrich_holdings(holdings: list[dict[str, Any]]) -> list[dict[str, Any]]:
        enriched = []
        for h in holdings:
            market_value = h["shares"] * h["current_price"]
            cost_value = h["shares"] * h["cost_basis_per_share"]
            enriched.append(
                {
                    **h,
                    "market_value": market_value,
                    "unrealized_pl": market_value - cost_value,
                    "unrealized_pl_pct": (market_value - cost_value) / cost_value if cost_value else None,
                }
            )
        return enriched


def load_default_adapter() -> PortfolioAdapter:
    """The single place a live adapter would be swapped in later."""
    return MockPortfolioAdapter()
