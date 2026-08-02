"""Read-only portfolio adapter contract.

This is the entire surface any account-data source may expose to the rest of
the system. Note what is *not* here: nothing to place, modify, or cancel an
order; nothing that mutates account state in any way. A future brokerage
integration only ever needs to implement these two methods, and by
construction it has no method to expose that could execute a trade.
"""

from __future__ import annotations

from typing import Any, Protocol


class PortfolioAdapter(Protocol):
    """Contract for any source of portfolio/account context.

    Implementations must be read-only: fetching data and returning it. If an
    implementation needs credentials, those credentials must be scoped to
    read-only permissions at the provider (e.g. an OAuth scope or API key
    tier that cannot place orders), so that even a bug in this codebase
    cannot result in a trade being placed.
    """

    def get_snapshot(self) -> dict[str, Any]:
        """Return the full account snapshot: cash, holdings, watchlist."""
        ...

    def get_holding(self, ticker: str) -> dict[str, Any] | None:
        """Return detail for a single holding, or None if not held."""
        ...
