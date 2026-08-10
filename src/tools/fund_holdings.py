"""Full portfolio holdings for a fund, parsed from its N-PORT filing.

This is the module that makes fund research more than a vendor summary. An
ETF's complete portfolio is a matter of public record: every registered
fund files Form N-PORT quarterly, and the raw XML lists each position with
its name, CUSIP, ISIN, percent of net assets, and — usefully — its issuer
country. So holdings, concentration, and geographic exposure are all
filing-sourced facts here, not estimates and not vendor summaries.

Two structural details drive the design:

**One filing per series, many series per trust.** Vanguard Index Funds
files a separate N-PORT for each fund it registers, all on the same day,
and EDGAR's submissions index doesn't say which is which. The only way to
find the right one is to open them and read the ``seriesId`` inside. This
module therefore walks recent N-PORT filings until it finds the matching
series, capped so a miss can't turn into an unbounded crawl. Everything is
disk-cached, so the cost is paid once per fund per quarter.

**N-PORT lags.** A filing covers a quarter-end up to 60 days before it was
filed. Every result here carries that ``report_date``, and callers must
describe the data as of that date rather than as current holdings.

The URL detail worth knowing: EDGAR's submissions index points at an
XSL-rendered viewer path for these documents. Stripping the ``xslFormN...``
segment yields the raw XML, which is what this module parses.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from typing import Any

from src.tools.edgar_client import fetch_text
from src.tools.fund_filings import list_fund_filings
from src.tools.fund_registry import resolve_fund

# A trust can register dozens of funds and file an N-PORT for each. This
# bounds the search for the right series; raise it only if a large trust
# genuinely needs it.
_MAX_NPORT_PROBES = 20

_XSL_SEGMENT_RE = re.compile(r"/xslFormN[^/]*/")

# Issuer-name suffixes that differ between filers and vendors for the same
# company ("Microsoft Corp" vs "Microsoft Corporation") and so must be
# stripped before comparing.
_NAME_SUFFIXES = {
    "inc", "incorporated", "corp", "corporation", "co", "company", "ltd",
    "limited", "plc", "sa", "nv", "ag", "holdings", "holding", "group",
    "the", "class", "a", "b", "c", "cl", "common", "stock", "shares", "reg",
    # Connectives: a filer writes "Johnson & Johnson" where a vendor writes
    # "Johnson and Johnson", and the tokenizer already drops the ampersand.
    "and", "of",
}


def _raw_xml_url(url: str) -> str:
    """Convert EDGAR's XSL viewer URL for an N-PORT into the raw XML URL."""
    return _XSL_SEGMENT_RE.sub("/", url)


def _localname(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _findtext(element: ET.Element, name: str) -> str | None:
    for child in element.iter():
        if _localname(child.tag) == name and child.text:
            return child.text.strip()
    return None


def normalize_issuer_name(name: str) -> str:
    """Reduce an issuer name to a comparable core.

    Filers and data vendors disagree on legal suffixes and punctuation for
    the same company, so comparing raw strings misses obvious matches.
    """
    tokens = re.findall(r"[a-z0-9]+", (name or "").lower())
    core = [t for t in tokens if t not in _NAME_SUFFIXES]
    return " ".join(core or tokens)


def _parse_holdings(xml_text: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Parse an N-PORT XML document into holdings plus fund-level metadata."""
    root = ET.fromstring(xml_text)

    meta: dict[str, Any] = {
        "series_id": _findtext(root, "seriesId"),
        "series_name": _findtext(root, "seriesName"),
        "report_date": _findtext(root, "repPdDate") or _findtext(root, "repPdEnd"),
        "total_assets": _findtext(root, "totAssets"),
        "net_assets": _findtext(root, "netAssets"),
    }

    holdings: list[dict[str, Any]] = []
    for element in root.iter():
        if _localname(element.tag) != "invstOrSec":
            continue
        isin = None
        for child in element.iter():
            if _localname(child.tag) == "isin":
                isin = child.get("value") or (child.text or "").strip() or None
                break
        try:
            weight = float(_findtext(element, "pctVal") or "nan")
        except ValueError:
            weight = float("nan")
        name = _findtext(element, "name")
        holdings.append(
            {
                "name": name,
                "normalized_name": normalize_issuer_name(name or ""),
                "cusip": _findtext(element, "cusip"),
                "isin": isin,
                "weight": None if weight != weight else weight / 100.0,  # pctVal is a percent
                "country": _findtext(element, "invCountry"),
                "asset_category": _findtext(element, "assetCat"),
            }
        )
    return holdings, meta


def fetch_fund_holdings(ticker: str) -> dict[str, Any]:
    """Return a fund's full holdings from its most recent matching N-PORT filing.

    Returns ``{"status": "ok", "fund", "as_of", "holdings", "country_weights", ...}``
    or a ``{"status", "reason"}`` refusal.
    """
    resolution = resolve_fund(ticker)
    if resolution["status"] != "ok":
        return resolution

    symbol = resolution["ticker"]
    series_id = resolution["series_id"]
    filings = list_fund_filings(resolution["cik"], forms=("NPORT-P",), limit=_MAX_NPORT_PROBES)
    if not filings:
        return {
            "status": "no_filings",
            "ticker": symbol,
            "reason": f"No N-PORT filings found for CIK {resolution['cik']}.",
        }

    for filing in filings:
        url = _raw_xml_url(filing["url"])
        try:
            xml_text = fetch_text(url, cache_key=f"nport_{filing['accession_number']}")
            holdings, meta = _parse_holdings(xml_text)
        except Exception:
            continue  # an unreadable filing shouldn't stop the series search
        if meta.get("series_id") != series_id:
            continue

        country_weights: dict[str, float] = {}
        for holding in holdings:
            if holding["country"] and holding["weight"] is not None:
                country_weights[holding["country"]] = round(
                    country_weights.get(holding["country"], 0.0) + holding["weight"], 6
                )

        ranked = sorted(
            (h for h in holdings if h["weight"] is not None),
            key=lambda h: h["weight"],
            reverse=True,
        )
        return {
            "status": "ok",
            "ticker": symbol,
            "fund": {
                "series_id": series_id,
                "series_name": meta.get("series_name"),
                "cik": resolution["cik"],
            },
            "source": "filing",
            "form": "NPORT-P",
            "source_url": url,
            "filing_date": filing["filing_date"],
            "as_of": meta.get("report_date"),
            "staleness_warning": (
                f"Holdings are as of {meta.get('report_date')}, the N-PORT reporting period end. "
                "A fund files this up to 60 days after quarter end, so describe these as holdings "
                "on that date, never as current holdings."
            ),
            "holdings_count": len(holdings),
            "top_10_weight": round(sum(h["weight"] for h in ranked[:10]), 6) if ranked else None,
            "country_weights": dict(
                sorted(country_weights.items(), key=lambda kv: kv[1], reverse=True)
            ),
            "holdings": ranked,
        }

    return {
        "status": "series_not_found",
        "ticker": symbol,
        "reason": (
            f"Checked the {len(filings)} most recent N-PORT filings for CIK {resolution['cik']} "
            f"and none reported series {series_id}. The trust may register more funds than that "
            "window covers."
        ),
    }
