"""Look-through exposure across the whole account, not one candidate fund.

``fund_overlap`` answers a question about a fund you are *considering*: "if I
add VOO, how much of it do I already own?" This module answers the question
about the account you *already have*: "counting through every fund I hold,
what am I actually exposed to?"

That question has no answer at the ticker level, and the ticker level is the
only level a brokerage statement shows. An account holding VOO, QQQ and a
direct NVDA position looks like three lines and reads as diversified; once the
funds are unpacked, the same handful of mega-cap issuers can appear in all
three, and the concentration lands precisely where the account is already
most exposed. Nothing in a positions list makes that visible.

Everything here is arithmetic over two kinds of input: the account snapshot
and, for each fund held, that fund's N-PORT holdings (a filing). An issuer's
look-through weight is the fund's weight in the account multiplied by the
issuer's weight in the fund, summed across funds, then added to any directly
held weight. No vendor figures, no estimates, no correlation model — so every
number returned is stamped ``computed`` with its inputs named.

Three honesty constraints, all inherited from the data:

**Matching.** Reuses ``fund_overlap``'s rule — exact on ISIN, falling back to
a normalized issuer name. Neither guesses. An unmatched fund holding is still
counted, under its filed issuer name rather than a ticker, so the arithmetic
stays complete even when the join fails.

**Unreadable funds are reported, never dropped.** A fund whose N-PORT can't
be retrieved keeps its account weight in ``funds_not_looked_through``. A
silently dropped fund would understate concentration, and understatement is
the dangerous direction of error here.

**Staleness.** Each fund's holdings are as of a quarter-end filed up to 60
days later, and different funds report different quarter-ends. Every
contributing date is listed; describe the result as of those dates, never as
current holdings.
"""

from __future__ import annotations

from typing import Any

from src.tools.fund_holdings import fetch_fund_holdings
from src.tools.fund_overlap import _identify_position
from src.tools.fund_registry import FundLookupError, resolve_fund
from src.tools.mock_portfolio import load_default_adapter

# A look-through weight only counts as "hidden" once it is a meaningful share
# of the account. Below this, the multiplier is arithmetically real but too
# small to be worth a reader's attention.
_HIDDEN_MIN_WEIGHT = 0.01
# Directly held weight has to grow by at least this multiple, once funds are
# counted, before the gap is worth calling out rather than rounding noise.
_HIDDEN_MIN_MULTIPLE = 1.25


def _classify(holdings: list[dict[str, Any]]) -> tuple[list[dict], list[dict]]:
    """Split account holdings into funds and direct positions.

    A ticker SEC's fund map resolves is treated as a fund; everything else is
    a direct position. ``resolve_fund`` reports an unsupported ticker as a
    status rather than raising, so a non-fund is an expected outcome here.
    """
    funds, direct = [], []
    for holding in holdings:
        if resolve_fund(holding["ticker"])["status"] == "ok":
            funds.append(holding)
        else:
            direct.append(holding)
    return funds, direct


def compute_true_exposure(top_n: int = 15) -> dict[str, Any]:
    """Aggregate issuer-level exposure across direct holdings and held funds.

    Returns ``{"status": "ok", ...}``, or a ``{"status", "reason"}`` refusal
    when SEC's fund mapping is unreachable and funds therefore can't be
    distinguished from stocks.
    """
    snapshot = load_default_adapter().get_snapshot()

    try:
        fund_positions, direct_positions = _classify(snapshot["holdings"])
    except FundLookupError as exc:
        return {
            "status": "fund_map_unavailable",
            "reason": (
                f"{exc} Without it, a held fund can't be told apart from a held stock, and "
                "reporting an unlooked-through account as a true exposure would overstate "
                "diversification."
            ),
        }

    # Identify direct positions once, so fund holdings can be matched back to
    # a ticker the account actually holds.
    identities = {h["ticker"]: _identify_position(h["ticker"]) for h in direct_positions}
    by_isin = {i["isin"]: t for t, i in identities.items() if i["isin"]}
    by_name = {i["normalized_name"]: t for t, i in identities.items() if i["normalized_name"]}
    by_compact = {
        i["normalized_name"].replace(" ", ""): t
        for t, i in identities.items()
        if i["normalized_name"]
    }

    # exposure key -> accumulating record. The key is a held ticker where the
    # issuer could be matched to one, and a normalized issuer name otherwise.
    exposure: dict[str, dict[str, Any]] = {}

    def _record(key: str, label: str) -> dict[str, Any]:
        return exposure.setdefault(
            key,
            {
                "key": key,
                "label": label,
                "held_directly": False,
                "direct_weight": 0.0,
                "look_through_weight": 0.0,
                "via_funds": [],
            },
        )

    for holding in direct_positions:
        ticker = holding["ticker"]
        weight = holding.get("weight") or 0.0
        record = _record(ticker, identities[ticker].get("name") or ticker)
        record["held_directly"] = True
        record["direct_weight"] += weight

    looked_through: list[dict[str, Any]] = []
    not_looked_through: list[dict[str, Any]] = []

    for holding in fund_positions:
        symbol = holding["ticker"]
        fund_weight = holding.get("weight") or 0.0
        fund = fetch_fund_holdings(symbol)
        if fund["status"] != "ok":
            not_looked_through.append(
                {
                    "ticker": symbol,
                    "weight_in_account": fund_weight,
                    "status": fund["status"],
                    "reason": fund.get("reason"),
                }
            )
            continue

        priced = [h for h in fund["holdings"] if h["weight"] is not None]
        for fund_holding in priced:
            matched = None
            if fund_holding["isin"] and fund_holding["isin"] in by_isin:
                matched = by_isin[fund_holding["isin"]]
            elif fund_holding["normalized_name"] in by_name:
                matched = by_name[fund_holding["normalized_name"]]
            elif fund_holding["normalized_name"].replace(" ", "") in by_compact:
                matched = by_compact[fund_holding["normalized_name"].replace(" ", "")]

            key = matched or fund_holding["normalized_name"] or fund_holding["name"]
            if not key:
                continue
            record = _record(key, fund_holding["name"] or key)
            contribution = fund_weight * fund_holding["weight"]
            record["look_through_weight"] += contribution
            record["via_funds"].append(
                {
                    "fund": symbol,
                    "weight_in_fund": fund_holding["weight"],
                    "contributed_weight": round(contribution, 8),
                }
            )

        looked_through.append(
            {
                "ticker": symbol,
                "weight_in_account": fund_weight,
                "series_name": fund["fund"].get("series_name"),
                "holdings_as_of": fund["as_of"],
                "holdings_count": fund["holdings_count"],
                "source_url": fund["source_url"],
                # How much of the fund its own filed weights account for. Well
                # short of 1.0 means the look-through through this fund is
                # partial, and the caller should say so.
                "weights_coverage": round(sum(h["weight"] for h in priced), 6),
            }
        )

    ranked = sorted(
        exposure.values(),
        key=lambda r: r["direct_weight"] + r["look_through_weight"],
        reverse=True,
    )
    for record in ranked:
        record["direct_weight"] = round(record["direct_weight"], 8)
        record["look_through_weight"] = round(record["look_through_weight"], 8)
        record["total_weight"] = round(record["direct_weight"] + record["look_through_weight"], 8)
        record["via_funds"].sort(key=lambda v: v["contributed_weight"], reverse=True)

    hidden = [
        {
            **record,
            "multiple_of_direct": (
                round(record["total_weight"] / record["direct_weight"], 2)
                if record["direct_weight"]
                else None
            ),
        }
        for record in ranked
        if record["total_weight"] >= _HIDDEN_MIN_WEIGHT
        and record["look_through_weight"] > 0
        and (
            not record["direct_weight"]
            or record["total_weight"] / record["direct_weight"] >= _HIDDEN_MIN_MULTIPLE
        )
    ]

    total_value = snapshot["total_portfolio_value"]
    cash_weight = snapshot["cash"] / total_value if total_value else None

    return {
        "status": "ok",
        "source": "computed",
        "basis": (
            "Computed by multiplying each held fund's weight in the account by each issuer's "
            "weight in that fund's N-PORT holdings, then adding directly held weights. Inputs: "
            "the account snapshot and one N-PORT filing per fund held — no vendor figures and "
            "no estimates."
        ),
        "inputs_used": {
            "account_as_of": snapshot["as_of"],
            "account_positions": len(snapshot["holdings"]),
            "direct_positions": len(direct_positions),
            "fund_positions": len(fund_positions),
            "cash_weight": cash_weight,
        },
        "funds_looked_through": looked_through,
        "funds_not_looked_through": not_looked_through,
        "issuer_count": len(ranked),
        "top_exposures": ranked[: max(top_n, 0)],
        "top_10_weight": round(sum(r["total_weight"] for r in ranked[:10]), 6),
        "hidden_concentration": hidden,
        "staleness_warning": (
            "Each fund's holdings are as of the N-PORT reporting period end listed against it, "
            "filed up to 60 days later, and different funds report different quarter-ends. State "
            "those dates; never describe this as current exposure."
        )
        if looked_through
        else None,
        "match_caveat": (
            "Fund holdings are matched to held tickers exactly on ISIN, falling back to a "
            "normalized issuer name; neither rule guesses. An unmatched issuer is still counted, "
            "under its filed name rather than a ticker, so a failed join splits one issuer across "
            "two rows rather than dropping it — read a name row and a ticker row for the same "
            "company as one exposure."
        ),
        "not_a_risk_model": (
            "This is weight arithmetic, not a risk or correlation model. It shows what share of "
            "the account each issuer represents once funds are unpacked; it says nothing about "
            "how those exposures move together."
        ),
    }
