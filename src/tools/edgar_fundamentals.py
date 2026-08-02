"""Extract deterministic fundamentals from a company's real XBRL filings.

Every number returned here comes directly from a value SEC's XBRL API
reports for a specific US-GAAP tag on a specific annual (10-K, fp="FY")
period — nothing is estimated or interpolated. If a company doesn't tag a
concept (common for smaller filers, or concepts reported under an
alternate tag), that field is simply left out rather than guessed; callers
must treat a missing key as "unknown," not "zero."

This produces a fundamentals dict shaped exactly like the ones hand-curated
in the local filing corpus's YAML front matter, so ``metrics_engine.compute_ratios``
works identically on live EDGAR data and the local excerpts.
"""

from __future__ import annotations

from typing import Any

from src.tools.edgar_client import EdgarLookupError, get_cik_for_ticker, get_company_facts, get_submissions

# Ordered by preference: the first tag a company actually reports wins.
# Companies vary in which concept they tag (e.g. some tag "Revenues", others
# "RevenueFromContractWithCustomerExcludingAssessedTax") — trying alternates
# in order is standard practice for XBRL consumption, not a guess about the
# value itself.
_TAG_ALTERNATES: dict[str, list[str]] = {
    "revenue": ["Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax"],
    "cogs": ["CostOfRevenue", "CostOfGoodsAndServicesSold"],
    "operating_income": ["OperatingIncomeLoss"],
    "net_income": ["NetIncomeLoss"],
    "cash_and_equivalents": ["CashAndCashEquivalentsAtCarryingValue"],
    "interest_expense": ["InterestExpense", "InterestExpenseDebt"],
    "current_assets": ["AssetsCurrent"],
    "current_liabilities": ["LiabilitiesCurrent"],
    "eps": ["EarningsPerShareDiluted"],
    "shares_outstanding": ["CommonStockSharesOutstanding"],
    "long_term_debt": ["LongTermDebtNoncurrent"],
    "short_term_debt": ["DebtCurrent", "LongTermDebtCurrent"],
}


def _annual_values(gaap_facts: dict[str, Any], tags: list[str]) -> list[dict[str, Any]]:
    """Return all 10-K/FY period observations for the first tag that has any, sorted oldest to newest."""
    for tag in tags:
        if tag not in gaap_facts:
            continue
        units = gaap_facts[tag].get("units", {})
        for unit_values in units.values():
            annual = [
                v
                for v in unit_values
                if v.get("form") == "10-K" and v.get("fp") == "FY" and "val" in v
            ]
            if annual:
                return sorted(annual, key=lambda v: v.get("end", ""))
    return []


def _latest_annual_value(gaap_facts: dict[str, Any], tags: list[str]) -> tuple[float | None, int | None]:
    """Return (value, fiscal_year) for the most recent 10-K/FY period, trying tags in order."""
    annual = _annual_values(gaap_facts, tags)
    if not annual:
        return None, None
    latest = annual[-1]
    return float(latest["val"]), latest.get("fy")


def _prior_annual_value(gaap_facts: dict[str, Any], tags: list[str]) -> float | None:
    """Return the second-most-recent annual value, or None if fewer than two exist."""
    annual = _annual_values(gaap_facts, tags)
    if len(annual) < 2:
        return None
    return float(annual[-2]["val"])


def fetch_live_fundamentals(ticker: str) -> dict[str, Any]:
    """Fetch and return a fundamentals dict for ticker, sourced from XBRL facts.

    Raises EdgarLookupError if the ticker can't be resolved to a CIK.
    Individual fundamentals fields are None if the company doesn't report
    that concept — never estimated.
    """
    cik = get_cik_for_ticker(ticker)
    if cik is None:
        raise EdgarLookupError(f"Could not resolve ticker '{ticker}' to a CIK via SEC EDGAR.")

    facts = get_company_facts(cik)
    gaap = facts.get("facts", {}).get("us-gaap", {})

    fundamentals: dict[str, Any] = {}
    fiscal_years: list[int] = []
    for field, tags in _TAG_ALTERNATES.items():
        value, fy = _latest_annual_value(gaap, tags)
        fundamentals[field] = value
        if fy is not None:
            fiscal_years.append(fy)

    # Derive total_debt from current + noncurrent components; None if both are missing.
    long_term = fundamentals.pop("long_term_debt")
    short_term = fundamentals.pop("short_term_debt")
    if long_term is not None or short_term is not None:
        fundamentals["total_debt"] = (long_term or 0.0) + (short_term or 0.0)
    else:
        fundamentals["total_debt"] = None

    fundamentals["prior_year_revenue"] = _prior_annual_value(gaap, _TAG_ALTERNATES["revenue"])
    fundamentals["prior_year_eps"] = _prior_annual_value(gaap, _TAG_ALTERNATES["eps"])

    # Not available from XBRL without further assumptions this module refuses
    # to make: EBITDA (companies don't tag it directly; deriving it requires
    # picking a D&A tag that isn't consistently reported) and market_cap
    # (requires a live share price, which is account/market data, not a
    # filing fact). Left None rather than estimated — pe_ratio and
    # ev_to_ebitda will be None for live-fetched tickers unless a caller
    # supplies market_cap separately.
    fundamentals["ebitda"] = None
    fundamentals["market_cap"] = None

    submissions = get_submissions(cik)
    company_name = submissions.get("name", ticker.upper())

    return {
        "ticker": ticker.upper(),
        "company": company_name,
        "cik": cik,
        "fiscal_year": max(fiscal_years) if fiscal_years else None,
        "source": "SEC EDGAR XBRL (live)",
        **fundamentals,
    }
