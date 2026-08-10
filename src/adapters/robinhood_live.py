"""Live, read-only Robinhood portfolio adapter.

This is the real implementation of the adapter that
``robinhood_readonly.py`` has always described in the abstract. It
satisfies the same ``PortfolioAdapter`` contract the mock does, so
everything downstream — the dashboard, the research tools, the weights and
P/L arithmetic — is unchanged by which one is in use.

It reads four things and derives the rest: accounts, the account's
portfolio value, its equity positions, and live quotes for the symbols
held. Weights, market values, and unrealized P/L are computed here from
those inputs, exactly as ``mock_portfolio`` computes them from its fixture,
rather than trusted from a vendor field.

One deviation from the mock worth knowing: the brokerage reports an average
buy price that already accounts for partial disposals, which is the figure
shown in the Robinhood app. That is used as cost basis directly. Positions
still reconciling may omit it, in which case cost basis and P/L come back
``None`` rather than zero — a missing cost basis is not a cost basis of nothing.

The watchlist stays local. A brokerage watchlist is a different list with
different semantics, and silently merging the two would make the user's own
tracking list unpredictable.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from src.adapters import rh_mcp_client
from src.tools.watchlist import get_watchlist


class RobinhoodLiveAdapter:
    """Read-only live account data. Implements the PortfolioAdapter protocol."""

    def __init__(self, account_number: str | None = None) -> None:
        self._account_number = account_number

    def resolve_account(self) -> dict[str, Any]:
        """Return the account to report on: the configured one, else the default."""
        accounts = rh_mcp_client.get_accounts()
        if not accounts:
            raise RuntimeError("Robinhood returned no brokerage accounts for this login.")
        if self._account_number:
            for account in accounts:
                if account.get("account_number") == self._account_number:
                    return account
            raise RuntimeError(
                f"Account {self._account_number} is not among this login's accounts."
            )
        for account in accounts:
            if account.get("is_default"):
                return account
        return accounts[0]

    def get_snapshot(self) -> dict[str, Any]:
        account = self.resolve_account()
        account_number = account["account_number"]

        portfolio = rh_mcp_client.get_portfolio(account_number)
        positions = rh_mcp_client.get_equity_positions(account_number)
        symbols = [p["symbol"] for p in positions if p.get("symbol")]
        quotes = rh_mcp_client.get_equity_quotes(symbols)

        holdings = [self._enrich(p, quotes.get(p.get("symbol", ""), {})) for p in positions]
        total_market_value = sum(h["market_value"] or 0.0 for h in holdings)
        cash = _as_float(portfolio.get("cash")) or 0.0
        total_portfolio_value = _as_float(portfolio.get("total_value"))
        if total_portfolio_value is None:
            total_portfolio_value = total_market_value + cash

        for holding in holdings:
            holding["weight"] = (
                (holding["market_value"] / total_portfolio_value)
                if holding["market_value"] is not None and total_portfolio_value
                else None
            )

        holdings.sort(key=lambda h: h["market_value"] or 0.0, reverse=True)

        return {
            "account_id": account_number,
            "account_nickname": account.get("nickname"),
            "source": "robinhood_live",
            "as_of": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "cash": cash,
            "buying_power": _as_float(
                (portfolio.get("buying_power") or {}).get("buying_power")
            ),
            "holdings": holdings,
            "watchlist": get_watchlist(),
            "total_market_value": total_market_value,
            "total_portfolio_value": total_portfolio_value,
            "agentic_allowed": account.get("agentic_allowed"),
        }

    def get_holding(self, ticker: str) -> dict[str, Any] | None:
        for holding in self.get_snapshot()["holdings"]:
            if holding["ticker"] == ticker.upper():
                return holding
        return None

    @staticmethod
    def _enrich(position: dict[str, Any], quote: dict[str, Any]) -> dict[str, Any]:
        shares = _as_float(position.get("quantity")) or 0.0
        price = quote.get("price")
        cost_per_share = _as_float(position.get("average_buy_price"))

        market_value = shares * price if price is not None else None
        cost_value = shares * cost_per_share if cost_per_share is not None else None
        unrealized = (
            market_value - cost_value
            if market_value is not None and cost_value is not None
            else None
        )
        previous_close = quote.get("previous_close")
        day_change = (
            (price - previous_close) * shares
            if price is not None and previous_close is not None
            else None
        )

        return {
            "ticker": position.get("symbol", "").upper(),
            "shares": shares,
            "cost_basis_per_share": cost_per_share,
            "current_price": price,
            "previous_close": previous_close,
            "market_value": market_value,
            "unrealized_pl": unrealized,
            "unrealized_pl_pct": (unrealized / cost_value) if unrealized is not None and cost_value else None,
            "day_change": day_change,
            # Shares locked up (stock grants, pending disposals) are not freely
            # disposable, and a portfolio view that hid that would mislead.
            "shares_available": _as_float(position.get("shares_available_for_sells")),
            "shares_held_for_grants": _as_float(position.get("shares_held_for_stock_grants")),
        }


def _as_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
