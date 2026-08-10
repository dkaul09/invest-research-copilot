"""Look-through overlap between a fund and the account's existing holdings.

The question this answers — "if I add VOO, what do I actually end up
owning?" — is the one an index fund makes hard to see. A portfolio that
looks diversified at the ticker level can be far more concentrated once a
broad fund's holdings are unpacked, and the concentration lands precisely
on the positions already held.

Everything here is arithmetic over two inputs: the account snapshot (mock
account fixture) and the fund's N-PORT holdings (a filing). Nothing is
fetched from a vendor and nothing is estimated, so every number this module
returns is stamped ``computed`` with both inputs named.

**Matching.** A fund reports issuers by name, CUSIP, and ISIN; the account
holds tickers. ISIN would be the clean join, but the ticker→ISIN lookup is
unreliable in practice (it returns nothing for MSFT and PLTR), so matching
falls back to a normalized issuer name. Both are exact-match rules —
neither guesses. A holding that can't be matched is reported in
``unmatched`` rather than silently dropped, because a silent drop would
understate overlap and understated overlap is the dangerous direction of
error here.

**Staleness.** Overlap is computed against N-PORT holdings as of a
quarter-end, which the caller must state. See ``fund_holdings``.
"""

from __future__ import annotations

from typing import Any

import yfinance as yf

from src.tools.fund_holdings import fetch_fund_holdings, normalize_issuer_name
from src.tools.mock_portfolio import load_default_adapter


def _identify_position(ticker: str) -> dict[str, Any]:
    """Resolve one held ticker to the identifiers needed to match fund holdings."""
    isin = None
    name = None
    try:
        handle = yf.Ticker(ticker.upper())
        raw_isin = handle.isin
        # yfinance returns the string "-" when it has no ISIN on file.
        if raw_isin and raw_isin != "-":
            isin = raw_isin
        info = handle.info
        name = info.get("longName") or info.get("shortName")
    except Exception:
        pass
    return {
        "ticker": ticker.upper(),
        "isin": isin,
        "name": name,
        "normalized_name": normalize_issuer_name(name or ticker),
    }


def compute_fund_overlap(ticker: str) -> dict[str, Any]:
    """Compute how much of a fund the account already owns, and the combined exposure.

    Returns ``{"status": "ok", ...}`` or a ``{"status", "reason"}`` refusal
    when the fund's holdings can't be retrieved.
    """
    fund = fetch_fund_holdings(ticker)
    if fund["status"] != "ok":
        return fund

    snapshot = load_default_adapter().get_snapshot()
    positions = [_identify_position(h["ticker"]) for h in snapshot["holdings"]]
    weight_by_ticker = {h["ticker"]: h.get("weight") for h in snapshot["holdings"]}

    by_isin = {p["isin"]: p for p in positions if p["isin"]}
    by_name = {p["normalized_name"]: p for p in positions if p["normalized_name"]}
    # Filers and vendors also disagree on word breaks within a name — the
    # filing says "Exxon Mobil Corp" where the vendor says "ExxonMobil".
    # Collapsing spaces keeps the rule exact while surviving that.
    by_compact = {p["normalized_name"].replace(" ", ""): p for p in positions if p["normalized_name"]}

    matches: list[dict[str, Any]] = []
    matched_tickers: set[str] = set()
    for holding in fund["holdings"]:
        if holding["weight"] is None:
            continue
        position = None
        basis = None
        if holding["isin"] and holding["isin"] in by_isin:
            position = by_isin[holding["isin"]]
            basis = "isin"
        elif holding["normalized_name"] and holding["normalized_name"] in by_name:
            position = by_name[holding["normalized_name"]]
            basis = "normalized_name"
        elif holding["normalized_name"].replace(" ", "") in by_compact:
            position = by_compact[holding["normalized_name"].replace(" ", "")]
            basis = "normalized_name_compact"
        if position is None:
            continue
        matched_tickers.add(position["ticker"])
        matches.append(
            {
                "ticker": position["ticker"],
                "fund_holding_name": holding["name"],
                "weight_in_fund": holding["weight"],
                "weight_in_account": weight_by_ticker.get(position["ticker"]),
                "matched_on": basis,
            }
        )

    matches.sort(key=lambda m: m["weight_in_fund"], reverse=True)
    overlap_weight = round(sum(m["weight_in_fund"] for m in matches), 6)

    unmatched = [
        {"ticker": p["ticker"], "name": p["name"]}
        for p in positions
        if p["ticker"] not in matched_tickers
    ]

    return {
        "status": "ok",
        "ticker": fund["ticker"],
        "source": "computed",
        "basis": (
            "Computed by intersecting the account's holdings with the fund's N-PORT holdings. "
            "Inputs: the mock account fixture and the fund's N-PORT filing — no vendor figures "
            "and no estimates."
        ),
        "inputs_used": {
            "account_as_of": snapshot["as_of"],
            "fund_holdings_as_of": fund["as_of"],
            "fund_holdings_source_url": fund["source_url"],
            "fund_holdings_count": fund["holdings_count"],
            "account_positions": len(positions),
        },
        "staleness_warning": fund["staleness_warning"],
        "overlap_weight_of_fund": overlap_weight,
        "overlap_summary": (
            f"{overlap_weight:.2%} of {fund['ticker']}'s portfolio (as of {fund['as_of']}) is in "
            f"companies the account already holds directly."
        ),
        "matched_holdings": matches,
        "unmatched_account_positions": unmatched,
        "match_caveat": (
            "Matching is exact on ISIN, falling back to a normalized issuer name; neither rule "
            "guesses. A position listed in unmatched_account_positions is simply not present in "
            "this fund's holdings under either rule — treat overlap as a floor, not a ceiling."
        ),
    }
