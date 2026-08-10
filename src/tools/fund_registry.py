"""Resolve a fund ticker to the SEC filer that actually files for it.

An ETF is not a company. It has no 10-K, no XBRL company facts, and no CIK
of its own in the ordinary ``company_tickers.json`` map that
``edgar_client.get_cik_for_ticker`` reads — which is exactly why every
existing tool in this project dead-ends on VOO or VXUS. What a fund does
have is a registrant (a trust) that files on its behalf, and SEC publishes
a separate mapping for that: ``company_tickers_mf.json``, keyed by fund
ticker, giving the trust's CIK plus the series and class IDs that identify
the specific fund inside it.

This module is the gate every other fund tool goes through. Its job is as
much refusal as resolution: a ticker that isn't in the fund map gets an
explicit, typed reason rather than a guess. There are three distinct ways
a lookup legitimately fails, and collapsing them into one "not found"
would lose information the caller needs:

- ``not_a_fund`` — it resolves in the *company* map instead. AAPL belongs
  on the equity path; say so and name it.
- ``not_covered`` — a real fund this project can't ground. Two cases share
  this: non-US/UCITS funds (VUSA, CSPX), which have no EDGAR presence at
  all, and US unit investment trusts like SPY, which are absent from the
  fund mapping because they file under a different regime. Both are
  "genuinely a fund, genuinely unsupported" — never answer from memory.
- ``unknown`` — in neither map. Probably a typo, possibly delisted.

The caller is expected to surface these verbatim and ask, not paper over
them. A fabricated expense ratio is worse than no answer.
"""

from __future__ import annotations

import urllib.error
from typing import Any

from src.tools.edgar_client import fetch_json, get_cik_for_ticker

_FUND_TICKER_URL = "https://www.sec.gov/files/company_tickers_mf.json"

# Funds that are real, US-listed, and widely asked about, but absent from
# company_tickers_mf.json because they're structured as unit investment
# trusts rather than open-end funds. Naming them explicitly turns a
# confusing "unknown ticker" into an accurate explanation.
_KNOWN_UIT_FUNDS = {
    "SPY": "SPDR S&P 500 ETF Trust",
    "DIA": "SPDR Dow Jones Industrial Average ETF Trust",
    "MDY": "SPDR S&P MidCap 400 ETF Trust",
}


class FundLookupError(Exception):
    """Raised when a fund ticker can't be resolved to an SEC filer."""


def _load_fund_map() -> dict[str, dict[str, Any]]:
    """Return {TICKER: {cik, series_id, class_id}} from SEC's fund mapping.

    The raw payload is column-oriented (``fields`` + ``data`` rows), so this
    reshapes it once into a ticker-keyed dict. Cached to disk by fetch_json.
    """
    payload = fetch_json(_FUND_TICKER_URL, cache_key="company_tickers_mf")
    fields = payload["fields"]
    i_cik = fields.index("cik")
    i_series = fields.index("seriesId")
    i_class = fields.index("classId")
    i_symbol = fields.index("symbol")

    mapping: dict[str, dict[str, Any]] = {}
    for row in payload["data"]:
        symbol = str(row[i_symbol]).upper()
        if not symbol:
            continue
        # A ticker appears once per share class; the first row is the one
        # whose class the ticker actually names, so don't overwrite it.
        mapping.setdefault(
            symbol,
            {
                "cik": str(row[i_cik]).zfill(10),
                "series_id": row[i_series],
                "class_id": row[i_class],
            },
        )
    return mapping


def resolve_fund(ticker: str) -> dict[str, Any]:
    """Resolve a fund ticker to its SEC filer, or explain why it can't be.

    Returns either::

        {"status": "ok", "ticker", "cik", "series_id", "class_id"}

    or ``{"status": <not_a_fund|not_covered|unknown>, "ticker", "reason"}``.
    Never raises for an unrecognized ticker — an unsupported fund is an
    expected outcome to report, not an error to swallow.
    """
    symbol = ticker.strip().upper()
    if not symbol:
        return {"status": "unknown", "ticker": symbol, "reason": "No ticker was given."}

    try:
        fund_map = _load_fund_map()
    except (urllib.error.URLError, urllib.error.HTTPError, KeyError, ValueError) as exc:
        raise FundLookupError(
            f"Could not load SEC's fund ticker mapping ({exc}). Fund lookups need "
            "company_tickers_mf.json from sec.gov; without it nothing here can be grounded."
        ) from exc

    entry = fund_map.get(symbol)
    if entry is not None:
        return {
            "status": "ok",
            "ticker": symbol,
            "cik": entry["cik"],
            "series_id": entry["series_id"],
            "class_id": entry["class_id"],
            "source": "SEC company_tickers_mf.json",
        }

    if symbol in _KNOWN_UIT_FUNDS:
        return {
            "status": "not_covered",
            "ticker": symbol,
            "reason": (
                f"{symbol} ({_KNOWN_UIT_FUNDS[symbol]}) is a unit investment trust, not an "
                "open-end fund, so it isn't in SEC's fund ticker mapping and this project "
                "can't ground a memo on it. Ask about an equivalent open-end fund instead "
                "(for S&P 500 exposure: VOO or IVV)."
            ),
        }

    # Falling back to the company map distinguishes "you gave me a stock"
    # from "I've never heard of this", which are very different corrections.
    company_cik = get_cik_for_ticker(symbol)
    if company_cik is not None:
        return {
            "status": "not_a_fund",
            "ticker": symbol,
            "reason": (
                f"{symbol} is an operating company (CIK {company_cik}), not a fund. Use the "
                "equity tools — fetch_live_fundamentals and search_live_filings — instead."
            ),
        }

    return {
        "status": "unknown",
        "ticker": symbol,
        "reason": (
            f"'{symbol}' isn't in SEC's fund mapping or its company mapping. If it's a "
            "non-US or UCITS fund (for example VUSA or CSPX), this project covers "
            "US-domiciled funds only and has no data source for it — ask rather than "
            "assume it's equivalent to a US-listed fund with a similar name."
        ),
    }
