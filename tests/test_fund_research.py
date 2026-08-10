"""Tests for the fund research path.

These check the properties that keep a fund memo honest rather than the
arithmetic, which is trivial. Specifically: that an unsupported ticker
produces a *typed reason* instead of an answer, that N-PORT parsing yields
filing-sourced holdings and country weights, that overlap matching never
silently drops a position, and that vendor figures stay labelled as vendor
figures. No test here touches the network.
"""

from __future__ import annotations

import pytest

from src.tools import fund_compare, fund_holdings, fund_overlap, fund_registry
from src.tools.fund_holdings import normalize_issuer_name

FUND_MAP_PAYLOAD = {
    "fields": ["cik", "seriesId", "classId", "symbol"],
    "data": [
        [36405, "S000002839", "C000092055", "VOO"],
        [736054, "S000002932", "C000094038", "VXUS"],
    ],
}

NPORT_XML = """<?xml version="1.0"?>
<edgarSubmission>
  <genInfo><seriesId>S000002839</seriesId><seriesName>TEST 500 INDEX FUND</seriesName>
    <repPdDate>2026-03-31</repPdDate></genInfo>
  <invstOrSecs>
    <invstOrSec><name>Apple Inc</name><cusip>037833100</cusip>
      <identifiers><isin value="US0378331005"/></identifiers>
      <pctVal>6.500000</pctVal><invCountry>US</invCountry><assetCat>EC</assetCat></invstOrSec>
    <invstOrSec><name>Exxon Mobil Corp</name><cusip>30231G102</cusip>
      <identifiers><isin value="US30231G1022"/></identifiers>
      <pctVal>1.500000</pctVal><invCountry>US</invCountry><assetCat>EC</assetCat></invstOrSec>
    <invstOrSec><name>ASML Holding NV</name><cusip>N07059210</cusip>
      <identifiers><isin value="NL0010273215"/></identifiers>
      <pctVal>2.000000</pctVal><invCountry>NL</invCountry><assetCat>EC</assetCat></invstOrSec>
  </invstOrSecs>
</edgarSubmission>
"""


@pytest.fixture
def fund_map(monkeypatch):
    """Serve SEC's fund ticker mapping from a fixture instead of the network."""
    monkeypatch.setattr(fund_registry, "fetch_json", lambda url, cache_key: FUND_MAP_PAYLOAD)
    return FUND_MAP_PAYLOAD


class TestRegistry:
    def test_resolves_a_known_fund_to_its_filer(self, fund_map):
        result = fund_registry.resolve_fund("voo")
        assert result["status"] == "ok"
        assert result["cik"] == "0000036405"
        assert result["series_id"] == "S000002839"

    def test_an_operating_company_is_named_as_such(self, fund_map, monkeypatch):
        monkeypatch.setattr(fund_registry, "get_cik_for_ticker", lambda t: "0000320193")
        result = fund_registry.resolve_fund("AAPL")
        assert result["status"] == "not_a_fund"
        assert "equity tools" in result["reason"]

    def test_a_unit_investment_trust_is_refused_by_name(self, fund_map, monkeypatch):
        monkeypatch.setattr(fund_registry, "get_cik_for_ticker", lambda t: None)
        result = fund_registry.resolve_fund("SPY")
        assert result["status"] == "not_covered"
        assert "unit investment trust" in result["reason"]

    def test_an_unknown_ticker_points_at_the_us_only_scope(self, fund_map, monkeypatch):
        monkeypatch.setattr(fund_registry, "get_cik_for_ticker", lambda t: None)
        result = fund_registry.resolve_fund("CSPX")
        assert result["status"] == "unknown"
        assert "US-domiciled funds only" in result["reason"]

    def test_every_refusal_carries_a_reason(self, fund_map, monkeypatch):
        """A caller must always have something honest to say back."""
        monkeypatch.setattr(fund_registry, "get_cik_for_ticker", lambda t: None)
        for ticker in ("SPY", "CSPX", ""):
            result = fund_registry.resolve_fund(ticker)
            assert result["status"] != "ok"
            assert result["reason"]


class TestHoldingsParsing:
    def test_parses_holdings_with_weights_as_fractions(self):
        holdings, meta = fund_holdings._parse_holdings(NPORT_XML)
        assert meta["series_id"] == "S000002839"
        assert meta["report_date"] == "2026-03-31"
        apple = next(h for h in holdings if h["name"] == "Apple Inc")
        # pctVal is reported as a percent; the module stores a fraction.
        assert apple["weight"] == pytest.approx(0.065)
        assert apple["isin"] == "US0378331005"
        assert apple["country"] == "US"

    def test_country_weights_are_aggregated_from_the_filing(self, monkeypatch):
        holdings, _ = fund_holdings._parse_holdings(NPORT_XML)
        weights: dict[str, float] = {}
        for holding in holdings:
            weights[holding["country"]] = weights.get(holding["country"], 0.0) + holding["weight"]
        assert weights["US"] == pytest.approx(0.08)
        assert weights["NL"] == pytest.approx(0.02)

    def test_raw_xml_url_strips_the_xsl_viewer_segment(self):
        viewer = "https://www.sec.gov/Archives/edgar/data/36405/00000364/xslFormNPORT-P_X01/primary_doc.xml"
        assert fund_holdings._raw_xml_url(viewer).endswith("/00000364/primary_doc.xml")


class TestNameNormalization:
    @pytest.mark.parametrize(
        "left,right",
        [
            ("Microsoft Corp", "Microsoft Corporation"),
            ("Johnson & Johnson", "Johnson and Johnson"),
            ("Palantir Technologies Inc", "Palantir Technologies"),
        ],
    )
    def test_legal_suffixes_do_not_block_a_match(self, left, right):
        assert normalize_issuer_name(left) == normalize_issuer_name(right)

    def test_distinct_issuers_still_differ(self):
        assert normalize_issuer_name("Apple Inc") != normalize_issuer_name("Apple Hospitality REIT")


class TestOverlap:
    """Overlap must never silently understate itself."""

    @pytest.fixture
    def patched(self, monkeypatch):
        holdings, meta = fund_holdings._parse_holdings(NPORT_XML)
        ranked = sorted(holdings, key=lambda h: h["weight"], reverse=True)
        monkeypatch.setattr(
            fund_overlap,
            "fetch_fund_holdings",
            lambda ticker: {
                "status": "ok",
                "ticker": ticker.upper(),
                "holdings": ranked,
                "holdings_count": len(ranked),
                "as_of": meta["report_date"],
                "source_url": "https://example.test/nport.xml",
                "staleness_warning": "as-of warning",
            },
        )

        class _Adapter:
            def get_snapshot(self):
                return {
                    "as_of": "2026-06-30",
                    "holdings": [
                        {"ticker": "AAPL", "weight": 0.20},
                        {"ticker": "XOM", "weight": 0.10},
                        {"ticker": "NKE", "weight": 0.05},
                    ],
                }

        monkeypatch.setattr(fund_overlap, "load_default_adapter", lambda: _Adapter())

    def test_matches_on_isin_and_on_a_spacing_variant(self, patched, monkeypatch):
        # XOM's vendor name ("ExxonMobil") differs from the filing's
        # ("Exxon Mobil") only by a space — it must still match.
        identities = {
            "AAPL": {"isin": "US0378331005", "name": "Apple Inc."},
            "XOM": {"isin": None, "name": "ExxonMobil Corporation"},
            "NKE": {"isin": None, "name": "NIKE, Inc."},
        }
        monkeypatch.setattr(
            fund_overlap,
            "_identify_position",
            lambda t: {
                "ticker": t.upper(),
                "isin": identities[t.upper()]["isin"],
                "name": identities[t.upper()]["name"],
                "normalized_name": normalize_issuer_name(identities[t.upper()]["name"]),
            },
        )

        result = fund_overlap.compute_fund_overlap("VOO")
        assert result["status"] == "ok"
        matched = {m["ticker"]: m for m in result["matched_holdings"]}
        assert matched["AAPL"]["matched_on"] == "isin"
        assert matched["XOM"]["matched_on"] == "normalized_name_compact"
        assert result["overlap_weight_of_fund"] == pytest.approx(0.08)

    def test_an_unmatched_position_is_reported_not_dropped(self, patched, monkeypatch):
        monkeypatch.setattr(
            fund_overlap,
            "_identify_position",
            lambda t: {
                "ticker": t.upper(),
                "isin": None,
                "name": t.upper(),
                "normalized_name": normalize_issuer_name(t),
            },
        )
        result = fund_overlap.compute_fund_overlap("VOO")
        unmatched = {u["ticker"] for u in result["unmatched_account_positions"]}
        assert unmatched == {"AAPL", "XOM", "NKE"}
        assert result["overlap_weight_of_fund"] == 0

    def test_result_is_stamped_computed_with_its_inputs(self, patched, monkeypatch):
        monkeypatch.setattr(
            fund_overlap,
            "_identify_position",
            lambda t: {"ticker": t.upper(), "isin": None, "name": t, "normalized_name": t.lower()},
        )
        result = fund_overlap.compute_fund_overlap("VOO")
        assert result["source"] == "computed"
        assert result["inputs_used"]["fund_holdings_as_of"] == "2026-03-31"
        assert result["inputs_used"]["account_as_of"] == "2026-06-30"
        assert result["staleness_warning"]


class TestCompare:
    def test_equal_fees_are_reported_as_a_tie(self, monkeypatch):
        def fake_profile(ticker):
            return {
                "status": "ok",
                "ticker": ticker.upper(),
                "identity": {"name": {"value": ticker.upper()}, "category": {"value": "Large Blend"},
                             "family": {"value": "X"}},
                "costs_and_scale": {
                    "expense_ratio": {"value": 0.0003},
                    "total_net_assets": {"value": 100.0},
                    "holdings_turnover": {"value": 0.02},
                },
                "exposure": {"top_10_weight": {"value": 0.36}},
            }

        monkeypatch.setattr(fund_compare, "get_fund_profile", fake_profile)
        result = fund_compare.compare_funds(["VOO", "IVV"])
        assert result["lowest_expense_ratio_tickers"] == ["VOO", "IVV"]

    def test_unsupported_tickers_are_listed_never_invented(self, monkeypatch):
        monkeypatch.setattr(
            fund_compare,
            "get_fund_profile",
            lambda t: {"status": "not_a_fund", "reason": "AAPL is an operating company"},
        )
        result = fund_compare.compare_funds(["AAPL"])
        assert result["funds"] == []
        assert result["unavailable"][0]["ticker"] == "AAPL"
        assert result["unavailable"][0]["reason"]
