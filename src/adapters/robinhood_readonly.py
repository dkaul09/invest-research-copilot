"""Future adapter: read-only Robinhood account context.

NOT IMPLEMENTED. This file exists to document the intended shape of a live
integration and the safety constraints it must satisfy before it is ever
wired in. Do not implement order-placing methods on this class, and do not
add methods beyond the ``PortfolioAdapter`` contract in ``base.py``.

Constraints for the eventual implementation:
  - Authenticate with the narrowest available read-only scope. If the
    provider's API does not support scoped read-only credentials, this
    adapter must not be built against that API in its current form.
  - Only call endpoints that fetch data: positions, watchlist, account
    cash balance, cost basis. Never import or call any endpoint capable of
    submitting, modifying, or canceling an order (e.g. anything resembling
    ``place_order``, ``submit_order``, ``cancel_order``, ``buy``, ``sell``).
  - This module must have zero dependency on any trading/execution library
    surface. If the only available Python client bundles order-placing
    functions in the same object as read endpoints, wrap it defensively so
    those methods are never imported or reachable from this codebase.
  - The PreToolUse hook (``.claude/hooks/block_trading_tools.py``) denies any
    tool call whose name or arguments look like order execution, as a
    second, independent layer of defense in case this file is ever misused.
"""

from __future__ import annotations

from typing import Any

from src.adapters.base import PortfolioAdapter


class RobinhoodReadOnlyAdapter(PortfolioAdapter):
    """Placeholder for a future read-only Robinhood integration."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        raise NotImplementedError(
            "RobinhoodReadOnlyAdapter is a documented future adapter, not yet "
            "implemented. Use MockPortfolioAdapter for the MVP."
        )

    def get_snapshot(self) -> dict[str, Any]:
        raise NotImplementedError

    def get_holding(self, ticker: str) -> dict[str, Any] | None:
        raise NotImplementedError
