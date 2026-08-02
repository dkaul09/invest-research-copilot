"""Live EDGAR adapter: XBRL extraction never estimates, retrieval carries a
real citation, and the module never calls a network endpoint that could
write anything (GET-only, public data only).

These tests monkeypatch the HTTP layer (edgar_client.fetch_json/fetch_text)
with fixture data rather than hitting the real network, so they run
deterministically offline and don't depend on SEC's live filings changing.
"""

from __future__ import annotations

import pytest

from src.tools import edgar_client, edgar_filings, edgar_fundamentals

FAKE_TICKER_MAP = {
    "0": {"cik_str": 1234567, "ticker": "ACME", "title": "Acme Corp"},
}

FAKE_SUBMISSIONS = {
    "name": "Acme Corp",
    "filings": {
        "recent": {
            "accessionNumber": ["0001234567-24-000010", "0001234567-23-000009"],
            "primaryDocument": ["acme-20231231.htm", "acme-20221231.htm"],
            "filingDate": ["2024-02-15", "2023-02-15"],
            "reportDate": ["2023-12-31", "2022-12-31"],
            "form": ["10-K", "10-K"],
        }
    },
}

FAKE_COMPANY_FACTS = {
    "facts": {
        "us-gaap": {
            "Revenues": {
                "units": {
                    "USD": [
                        {"end": "2022-12-31", "val": 800.0, "form": "10-K", "fp": "FY", "fy": 2022},
                        {"end": "2023-12-31", "val": 1000.0, "form": "10-K", "fp": "FY", "fy": 2023},
                    ]
                }
            },
            "CostOfRevenue": {
                "units": {"USD": [{"end": "2023-12-31", "val": 400.0, "form": "10-K", "fp": "FY", "fy": 2023}]}
            },
            "OperatingIncomeLoss": {
                "units": {"USD": [{"end": "2023-12-31", "val": 300.0, "form": "10-K", "fp": "FY", "fy": 2023}]}
            },
            "NetIncomeLoss": {
                "units": {"USD": [{"end": "2023-12-31", "val": 200.0, "form": "10-K", "fp": "FY", "fy": 2023}]}
            },
            "EarningsPerShareDiluted": {
                "units": {
                    "USD/shares": [
                        {"end": "2022-12-31", "val": 1.5, "form": "10-K", "fp": "FY", "fy": 2022},
                        {"end": "2023-12-31", "val": 2.0, "form": "10-K", "fp": "FY", "fy": 2023},
                    ]
                }
            },
            # Deliberately omit CashAndCashEquivalents, debt, and interest tags
            # so we can assert those fields come back None rather than guessed.
        }
    }
}


@pytest.fixture(autouse=True)
def patch_edgar_http(monkeypatch):
    def fake_fetch_json(url, cache_key, force_refresh=False):
        if "company_tickers" in url:
            return FAKE_TICKER_MAP
        if "submissions" in url:
            return FAKE_SUBMISSIONS
        if "companyfacts" in url:
            return FAKE_COMPANY_FACTS
        raise AssertionError(f"unexpected URL in test: {url}")

    def fake_fetch_text(url, cache_key, force_refresh=False):
        return "<html><body><p>" + ("Risk factor discussion about supply chain. " * 40) + "</p></body></html>"

    monkeypatch.setattr(edgar_client, "fetch_json", fake_fetch_json)
    monkeypatch.setattr(edgar_client, "fetch_text", fake_fetch_text)
    # edgar_filings imports fetch_text directly into its own namespace, so
    # the module-level patch above doesn't reach it — patch it there too.
    monkeypatch.setattr(edgar_filings, "fetch_text", fake_fetch_text)


def test_cik_lookup_resolves_known_ticker():
    assert edgar_client.get_cik_for_ticker("ACME") == "0001234567"


def test_cik_lookup_returns_none_for_unknown_ticker():
    assert edgar_client.get_cik_for_ticker("NOTATICKER") is None


def test_fundamentals_uses_real_xbrl_values_not_estimates():
    fundamentals = edgar_fundamentals.fetch_live_fundamentals("ACME")
    assert fundamentals["revenue"] == 1000.0
    assert fundamentals["cogs"] == 400.0
    assert fundamentals["operating_income"] == 300.0
    assert fundamentals["net_income"] == 200.0
    assert fundamentals["eps"] == 2.0
    assert fundamentals["prior_year_revenue"] == 800.0
    assert fundamentals["prior_year_eps"] == 1.5


def test_fundamentals_missing_tags_are_none_not_guessed():
    fundamentals = edgar_fundamentals.fetch_live_fundamentals("ACME")
    assert fundamentals["cash_and_equivalents"] is None
    assert fundamentals["total_debt"] is None
    assert fundamentals["interest_expense"] is None
    # Never derived from XBRL in this MVP — must stay None, not estimated.
    assert fundamentals["ebitda"] is None
    assert fundamentals["market_cap"] is None


def test_fundamentals_compatible_with_metrics_engine():
    from src.tools.metrics_engine import compute_ratios

    fundamentals = edgar_fundamentals.fetch_live_fundamentals("ACME")
    result = compute_ratios(fundamentals)
    assert result["ratios"]["gross_margin"] == pytest.approx((1000 - 400) / 1000)
    # Ratios needing a field we don't have must be None, never guessed.
    assert result["ratios"]["net_debt_to_ebitda"] is None
    assert result["ratios"]["pe_ratio"] is None


def test_unknown_ticker_raises_lookup_error_not_fabricated_data():
    with pytest.raises(edgar_client.EdgarLookupError):
        edgar_fundamentals.fetch_live_fundamentals("NOTATICKER")


def test_live_filing_search_returns_real_source_url():
    result = edgar_filings.search_live_filing("ACME", "supply chain", top_k=2)
    assert result["results"], "expected at least one chunk to match 'supply chain'"
    for hit in result["results"]:
        assert hit["source_url"].startswith("https://www.sec.gov/Archives/edgar/")
    assert result["filing"]["accession_number"] == "0001234567-24-000010"


def test_live_filing_search_unknown_ticker_raises():
    with pytest.raises(edgar_client.EdgarLookupError):
        edgar_filings.search_live_filing("NOTATICKER", "risk")
