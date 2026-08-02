"""Deterministic financial metric computation.

Every function here is a pure calculation over plain numbers. Nothing in this
module calls an LLM, makes a network request, or estimates a value it wasn't
given. When an input needed for a ratio is missing or would divide by zero,
the function returns ``None`` for that metric rather than guessing — a
research note must never state a number this module didn't produce.

Each public function returns a dict of the computed value(s) *and* the raw
inputs it used, so a caller (or a citation in a research note) can trace any
number back to the fundamentals it came from.
"""

from __future__ import annotations

from typing import Any


def _safe_div(numerator: float | None, denominator: float | None) -> float | None:
    """Divide two numbers, returning None instead of raising or guessing."""
    if numerator is None or denominator is None:
        return None
    if denominator == 0:
        return None
    return numerator / denominator


def compute_ratios(fundamentals: dict[str, Any]) -> dict[str, Any]:
    """Compute quality, leverage, and valuation ratios for one company.

    ``fundamentals`` is expected to hold keys such as revenue, cogs,
    operating_income, net_income, total_debt, cash_and_equivalents, ebitda,
    interest_expense, current_assets, current_liabilities,
    shares_outstanding, eps, prior_year_revenue, prior_year_eps, market_cap.
    Any missing key simply yields None for the ratios that depend on it.
    """
    f = fundamentals
    revenue = f.get("revenue")
    cogs = f.get("cogs")
    operating_income = f.get("operating_income")
    net_income = f.get("net_income")
    total_debt = f.get("total_debt")
    cash = f.get("cash_and_equivalents")
    ebitda = f.get("ebitda")
    interest_expense = f.get("interest_expense")
    current_assets = f.get("current_assets")
    current_liabilities = f.get("current_liabilities")
    market_cap = f.get("market_cap")
    eps = f.get("eps")
    prior_revenue = f.get("prior_year_revenue")
    prior_eps = f.get("prior_year_eps")

    gross_profit = None
    if revenue is not None and cogs is not None:
        gross_profit = revenue - cogs

    net_debt = None
    if total_debt is not None and cash is not None:
        net_debt = total_debt - cash

    ratios = {
        "gross_margin": _safe_div(gross_profit, revenue),
        "operating_margin": _safe_div(operating_income, revenue),
        "net_margin": _safe_div(net_income, revenue),
        "net_debt_to_ebitda": _safe_div(net_debt, ebitda),
        "interest_coverage": _safe_div(operating_income, interest_expense),
        "current_ratio": _safe_div(current_assets, current_liabilities),
        "revenue_growth_yoy": _safe_div(
            (revenue - prior_revenue) if revenue is not None and prior_revenue is not None else None,
            prior_revenue,
        ),
        "eps_growth_yoy": _safe_div(
            (eps - prior_eps) if eps is not None and prior_eps is not None else None,
            prior_eps,
        ),
        "pe_ratio": _safe_div(market_cap, net_income),
        "ev_to_ebitda": _safe_div(
            (market_cap + net_debt) if market_cap is not None and net_debt is not None else None,
            ebitda,
        ),
    }

    return {
        "ratios": ratios,
        "inputs_used": {
            "revenue": revenue,
            "cogs": cogs,
            "gross_profit": gross_profit,
            "operating_income": operating_income,
            "net_income": net_income,
            "total_debt": total_debt,
            "cash_and_equivalents": cash,
            "net_debt": net_debt,
            "ebitda": ebitda,
            "interest_expense": interest_expense,
            "current_assets": current_assets,
            "current_liabilities": current_liabilities,
            "market_cap": market_cap,
            "eps": eps,
            "prior_year_revenue": prior_revenue,
            "prior_year_eps": prior_eps,
        },
    }


def compute_concentration(
    holdings: list[dict[str, Any]],
) -> dict[str, Any]:
    """Compute portfolio concentration metrics from a list of position values.

    Each holding dict must have ``ticker`` and ``market_value``. Returns
    per-ticker weights, the Herfindahl-Hirschman Index (HHI) as a measure of
    concentration (0 = maximally diversified, 10000 = single position), and
    the weight of the single largest position.
    """
    total_value = sum(h["market_value"] for h in holdings)
    if total_value <= 0:
        return {"weights": {}, "hhi": None, "top_position_weight": None, "total_value": total_value}

    weights = {h["ticker"]: h["market_value"] / total_value for h in holdings}
    hhi = sum((w * 100) ** 2 for w in weights.values())
    top_position_weight = max(weights.values()) if weights else None

    return {
        "weights": weights,
        "hhi": hhi,
        "top_position_weight": top_position_weight,
        "total_value": total_value,
    }


def compute_sector_weights(
    holdings: list[dict[str, Any]],
) -> dict[str, float]:
    """Compute portfolio weight by sector. Each holding needs sector + market_value."""
    total_value = sum(h["market_value"] for h in holdings)
    if total_value <= 0:
        return {}
    sector_totals: dict[str, float] = {}
    for h in holdings:
        sector_totals[h["sector"]] = sector_totals.get(h["sector"], 0.0) + h["market_value"]
    return {sector: value / total_value for sector, value in sector_totals.items()}
