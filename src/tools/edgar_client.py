"""Low-level HTTP client for SEC EDGAR's free, keyless public APIs.

SEC EDGAR requires only a descriptive User-Agent identifying the requester
(no API key, no auth) — see https://www.sec.gov/os/webmaster-faq#developers.
Every response this module fetches is cached to disk under
``data/edgar_cache/`` (gitignored) so repeated questions about the same
ticker don't re-hit the network, and so this adapter degrades gracefully
offline once a ticker has been fetched once.

This module only ever performs GET requests against SEC's read-only,
public data endpoints. There is no write capability here to misuse.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

USER_AGENT = "invest-research-copilot dhruv.kaul@machina.gg"
CACHE_DIR = Path(__file__).resolve().parents[2] / "data" / "edgar_cache"

# SEC asks that automated tools stay under ~10 requests/second; this MVP
# makes at most a handful of sequential calls per ticker, so a small fixed
# delay between calls is a simple, sufficient way to stay well under that.
_MIN_REQUEST_INTERVAL_SECONDS = 0.15
_last_request_time = 0.0


def _throttle() -> None:
    global _last_request_time
    elapsed = time.monotonic() - _last_request_time
    if elapsed < _MIN_REQUEST_INTERVAL_SECONDS:
        time.sleep(_MIN_REQUEST_INTERVAL_SECONDS - elapsed)
    _last_request_time = time.monotonic()


def _cache_path(cache_key: str) -> Path:
    safe_key = cache_key.replace("/", "_").replace(":", "_")
    return CACHE_DIR / f"{safe_key}.json"


def fetch_json(url: str, cache_key: str, force_refresh: bool = False) -> dict[str, Any]:
    """GET a JSON endpoint, using the disk cache unless force_refresh is set."""
    cache_path = _cache_path(cache_key)
    if not force_refresh and cache_path.exists():
        with open(cache_path, "r", encoding="utf-8") as f:
            return json.load(f)

    _throttle()
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=20) as response:
        data = json.loads(response.read())

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    with open(cache_path, "w", encoding="utf-8") as f:
        json.dump(data, f)
    return data


def fetch_text(url: str, cache_key: str, force_refresh: bool = False) -> str:
    """GET a text/HTML endpoint, using the disk cache unless force_refresh is set."""
    cache_path = _cache_path(cache_key).with_suffix(".html")
    if not force_refresh and cache_path.exists():
        return cache_path.read_text(encoding="utf-8")

    _throttle()
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=20) as response:
        text = response.read().decode("utf-8", errors="replace")

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(text, encoding="utf-8")
    return text


class EdgarLookupError(Exception):
    """Raised when a ticker can't be resolved or has no usable filing data."""


def get_cik_for_ticker(ticker: str) -> str | None:
    """Resolve a ticker to a zero-padded 10-digit CIK, or None if unknown."""
    try:
        mapping = fetch_json(
            "https://www.sec.gov/files/company_tickers.json", cache_key="company_tickers"
        )
    except (urllib.error.URLError, urllib.error.HTTPError):
        return None

    ticker_upper = ticker.upper()
    for entry in mapping.values():
        if entry.get("ticker", "").upper() == ticker_upper:
            return str(entry["cik_str"]).zfill(10)
    return None


def get_submissions(cik: str) -> dict[str, Any]:
    return fetch_json(
        f"https://data.sec.gov/submissions/CIK{cik}.json", cache_key=f"submissions_{cik}"
    )


def get_company_facts(cik: str) -> dict[str, Any]:
    return fetch_json(
        f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json", cache_key=f"facts_{cik}"
    )


def get_latest_10k_filing(cik: str) -> dict[str, Any] | None:
    """Return {accession_number, primary_document, filing_date, report_date, url} for the most recent 10-K."""
    submissions = get_submissions(cik)
    recent = submissions["filings"]["recent"]
    forms = recent["form"]

    for i, form in enumerate(forms):
        if form == "10-K":
            accession = recent["accessionNumber"][i]
            accession_no_dashes = accession.replace("-", "")
            primary_doc = recent["primaryDocument"][i]
            cik_int = str(int(cik))  # EDGAR document URLs use the un-padded CIK
            url = (
                f"https://www.sec.gov/Archives/edgar/data/{cik_int}/"
                f"{accession_no_dashes}/{primary_doc}"
            )
            return {
                "accession_number": accession,
                "primary_document": primary_doc,
                "filing_date": recent["filingDate"][i],
                "report_date": recent["reportDate"][i],
                "url": url,
            }
    return None
