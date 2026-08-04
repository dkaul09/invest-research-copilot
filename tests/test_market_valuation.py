"""Tests for market-derived valuation multiples.

The point of these is provenance, not arithmetic: a multiple here mixes a
quoted price with filing figures, so every test checks that the result says
where it came from, and that a missing or meaningless input produces a
stated reason instead of a number.
"""

from __future__ import annotations

import pytest

from src.tools import market_valuation


BASE_FUNDAMENTALS = {
    "company": "Example Corp",
    "fiscal_year": 2025,
    "source": "SEC EDGAR XBRL (live)",
    "eps": 4.00,
    "shares_outstanding": 1_000_000_000.0,
    "ebitda": 5_000_000_000.0,
    "operating_income": 4_000_000_000.0,
    "depreciation_amortization": 1_000_000_000.0,
    "total_debt": 2_000_000_000.0,
    "cash_and_equivalents": 3_000_000_000.0,
}


@pytest.fixture
def patched(monkeypatch):
    """Patch both data sources so no test touches the network."""

    def apply(quote=None, **fundamental_overrides):
        fundamentals = {**BASE_FUNDAMENTALS, **fundamental_overrides}
        monkeypatch.setattr(
            market_valuation, "get_quote", lambda ticker: quote or {"ticker": ticker.upper(), "price": 100.0}
        )
        monkeypatch.setattr(market_valuation, "fetch_live_fundamentals", lambda ticker: fundamentals)

    return apply


def test_computes_multiples_from_price_and_filings(patched):
    patched()
    result = market_valuation.compute_market_valuation("EXMP")

    # P/E is price / diluted EPS: 100.00 / 4.00
    assert result["valuation"]["pe_ratio"] == pytest.approx(25.0)
    # Market cap is price x shares; EV adds net debt of (2bn - 3bn) = -1bn.
    assert result["valuation"]["market_cap"] == pytest.approx(100_000_000_000.0)
    assert result["valuation"]["enterprise_value"] == pytest.approx(99_000_000_000.0)
    assert result["valuation"]["ev_to_ebitda"] == pytest.approx(19.8)
    assert result["unavailable"] == {}


def test_result_carries_its_provenance(patched):
    """A market-derived number is only honest if it says so and says when."""
    patched()
    result = market_valuation.compute_market_valuation("EXMP")

    assert result["price"] == 100.0
    assert result["as_of"]
    assert "Market-derived" in result["basis"]
    assert result["inputs_used"]["eps"] == 4.00
    assert result["inputs_used"]["price_source"]
    assert result["inputs_used"]["fiscal_year"] == 2025


def test_negative_eps_yields_a_reason_not_a_number(patched):
    patched(eps=-2.50)
    result = market_valuation.compute_market_valuation("EXMP")

    assert result["valuation"]["pe_ratio"] is None
    assert "isn't meaningful" in result["unavailable"]["pe_ratio"]


def test_missing_ebitda_yields_a_reason_not_a_number(patched):
    patched(ebitda=None)
    result = market_valuation.compute_market_valuation("EXMP")

    assert result["valuation"]["ev_to_ebitda"] is None
    assert "D&A" in result["unavailable"]["ev_to_ebitda"]
    # P/E doesn't depend on EBITDA, so it still resolves.
    assert result["valuation"]["pe_ratio"] == pytest.approx(25.0)


def test_missing_share_count_still_allows_pe(patched):
    patched(shares_outstanding=None)
    result = market_valuation.compute_market_valuation("EXMP")

    assert result["valuation"]["market_cap"] is None
    assert result["valuation"]["ev_to_ebitda"] is None
    assert result["unavailable"]["market_cap"]
    assert result["valuation"]["pe_ratio"] == pytest.approx(25.0)


def test_quote_failure_returns_an_error_not_a_guess(patched):
    patched(quote={"ticker": "EXMP", "error": "Could not fetch quote: upstream down"})
    result = market_valuation.compute_market_valuation("EXMP")

    assert "error" in result
    assert "valuation" not in result
