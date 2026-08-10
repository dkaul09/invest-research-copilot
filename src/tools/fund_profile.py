"""The live, vendor-sourced half of a fund's profile.

Everything here comes from Yahoo Finance via yfinance. That is a vendor
summary, not a primary source, and this module never pretends otherwise:
every value it returns is wrapped as ``{value, source, as_of}`` with
``source="vendor"``, so a memo can state a fee or an AUM figure and say
where it came from in the same breath. Where a number is genuinely
primary-source-only — replication method, distribution policy, securities
lending — this module returns ``null`` and points at
``search_fund_filings`` rather than letting a vendor summary stand in for
a prospectus.

Three deliberate omissions, each of which would be easy to fabricate and
wrong to:

- **Yahoo's ``equity_holdings`` "Price/Earnings"** is an earnings yield,
  not a P/E — it reports 0.055 for VXUS. Surfacing it under Yahoo's label
  would put a mislabelled valuation multiple into a research memo, so the
  whole block is dropped rather than half-trusted.
- **Geographic exposure** has no country breakdown in this feed. Sector
  weights exist; country weights do not. Reported as null with that reason,
  because the honest source is the prospectus's stated mandate.
- **Tracking difference** needs the benchmark's total return, which no free
  source provides. Permanently null with the reason attached.

Top-10 concentration is the one number computed here rather than read, and
it is stamped ``computed`` with its inputs named.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import yfinance as yf

from src.tools.fund_registry import resolve_fund


def _stamp(value: Any, source: str, as_of: str, note: str | None = None) -> dict[str, Any]:
    """Wrap a value with where it came from and when."""
    stamped = {"value": value, "source": source, "as_of": as_of}
    if note:
        stamped["note"] = note
    return stamped


def _unavailable(reason: str) -> dict[str, Any]:
    """A field this project can't ground — null with a stated reason, never a guess."""
    return {"value": None, "source": None, "as_of": None, "unavailable": reason}


def get_fund_name(ticker: str) -> str | None:
    """Return the fund's long name, or None. Used to focus filing retrieval."""
    try:
        info = yf.Ticker(ticker.upper()).info
    except Exception:
        return None
    return info.get("longName") or info.get("shortName")


def _fund_operations_value(operations: Any, row_label: str, ticker: str) -> float | None:
    """Pull one labelled row from yfinance's fund_operations frame, or None."""
    try:
        if operations is None or operations.empty or row_label not in operations.index:
            return None
        value = operations.loc[row_label, ticker.upper()]
    except Exception:
        return None
    try:
        value = float(value)
    except (TypeError, ValueError):
        return None
    return None if value != value else value  # drop NaN rather than emit it


def get_fund_profile(ticker: str) -> dict[str, Any]:
    """Return a fund's vendor-sourced profile, every field stamped with its source.

    Returns a ``{"status", "reason"}`` refusal if the ticker isn't a
    supported US-listed fund.
    """
    resolution = resolve_fund(ticker)
    if resolution["status"] != "ok":
        return resolution

    symbol = resolution["ticker"]
    as_of = datetime.now(timezone.utc).isoformat(timespec="seconds")

    try:
        handle = yf.Ticker(symbol)
        funds = handle.funds_data
        info = handle.info
    except Exception as exc:
        return {
            "status": "vendor_error",
            "ticker": symbol,
            "reason": f"Could not fetch fund data for {symbol}: {exc}",
        }

    operations = getattr(funds, "fund_operations", None)
    expense_ratio = _fund_operations_value(operations, "Annual Report Expense Ratio", symbol)
    turnover = _fund_operations_value(operations, "Annual Holdings Turnover", symbol)
    net_assets = _fund_operations_value(operations, "Total Net Assets", symbol)

    try:
        overview = dict(funds.fund_overview or {})
    except Exception:
        overview = {}

    try:
        sector_weights = dict(funds.sector_weightings or {})
    except Exception:
        sector_weights = {}

    try:
        asset_classes = dict(funds.asset_classes or {})
    except Exception:
        asset_classes = {}

    try:
        description = funds.description
    except Exception:
        description = None

    top_holdings: list[dict[str, Any]] = []
    try:
        frame = funds.top_holdings
        if frame is not None and not frame.empty:
            for held_symbol, row in frame.iterrows():
                top_holdings.append(
                    {
                        "symbol": str(held_symbol),
                        "name": row.get("Name"),
                        "weight": float(row.get("Holding Percent")),
                    }
                )
    except Exception:
        top_holdings = []

    top_10_weight = sum(h["weight"] for h in top_holdings[:10]) if top_holdings else None

    return {
        "status": "ok",
        "ticker": symbol,
        "as_of": as_of,
        "basis": (
            "Vendor-sourced (Yahoo Finance via yfinance) unless a field says otherwise. "
            "Vendor figures are summaries, not primary sources — for anything a prospectus "
            "states directly (replication, distribution policy, securities lending), cite "
            "search_fund_filings instead."
        ),
        "identity": {
            "name": _stamp(info.get("longName") or info.get("shortName"), "vendor", as_of),
            "cik": _stamp(resolution["cik"], "filing", as_of, "SEC company_tickers_mf.json"),
            "series_id": _stamp(resolution["series_id"], "filing", as_of),
            "class_id": _stamp(resolution["class_id"], "filing", as_of),
            "legal_type": _stamp(overview.get("legalType"), "vendor", as_of),
            "family": _stamp(overview.get("family"), "vendor", as_of),
            "category": _stamp(overview.get("categoryName"), "vendor", as_of),
            "currency": _stamp(info.get("currency"), "vendor", as_of, "Trading currency — not the fund's underlying currency exposure."),
            "exchange": _stamp(info.get("fullExchangeName") or info.get("exchange"), "vendor", as_of),
            "domicile": _stamp(
                "United States", "filing", as_of,
                "Implied by registration with the SEC as a US open-end fund; this project covers US-domiciled funds only.",
            ),
        },
        "costs_and_scale": {
            "expense_ratio": _stamp(expense_ratio, "vendor", as_of, "Annual report expense ratio. The prospectus figure is the authoritative one — confirm via search_fund_filings."),
            "holdings_turnover": _stamp(turnover, "vendor", as_of),
            "total_net_assets": _stamp(net_assets, "vendor", as_of, "Reported in millions by the vendor feed."),
            "tracking_difference": _unavailable(
                "Requires the benchmark index's total return, which no free data source provides. "
                "Not estimated."
            ),
            "replication_method": _unavailable("Stated in the prospectus — retrieve via search_fund_filings."),
            "distribution_policy": _unavailable("Stated in the prospectus — retrieve via search_fund_filings."),
            "securities_lending": _unavailable("Disclosed in the N-CSR annual report — retrieve via search_fund_filings."),
        },
        "exposure": {
            "strategy_description": _stamp(description, "vendor", as_of, "Vendor summary of the mandate; the prospectus is authoritative."),
            "sector_weights": _stamp(sector_weights or None, "vendor", as_of),
            "asset_classes": _stamp(asset_classes or None, "vendor", as_of),
            "top_holdings": _stamp(top_holdings or None, "vendor", as_of),
            "top_10_weight": _stamp(
                top_10_weight, "computed", as_of,
                "Sum of the vendor-reported weights of the ten largest holdings.",
            ),
            "geographic_weights": _unavailable(
                "This feed reports sector weights but no country breakdown. Cite the prospectus's "
                "stated geographic mandate qualitatively instead of inventing percentages."
            ),
            "market_cap_weights": _unavailable(
                "No market-cap-band breakdown is available from this feed."
            ),
        },
    }
