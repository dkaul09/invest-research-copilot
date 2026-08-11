"""Tests for whole-account look-through exposure.

The arithmetic here is a multiplication, so these check the properties that
make the answer trustworthy instead: that a fund's weight is actually
multiplied through rather than counted at face value, that an issuer held
both directly and inside a fund lands in one row rather than two, that an
issuer held *only* through funds is surfaced at all (the entire point — it is
invisible in a positions list), and that a fund which can't be read keeps its
weight in the output instead of vanishing. A vanished fund would understate
concentration, which is the dangerous direction of error.

No test here touches the network.
"""

from __future__ import annotations

import pytest

from src.tools import true_exposure

# VOO-shaped: holds Apple (held directly by the account) and Nvidia (not).
VOO_HOLDINGS = [
    {"name": "Apple Inc", "normalized_name": "apple", "isin": "US0378331005", "weight": 0.07},
    {"name": "NVIDIA Corp", "normalized_name": "nvidia", "isin": "US67066G1040", "weight": 0.06},
]
# QQQ-shaped: overlaps VOO on both names, which must sum rather than replace.
QQQ_HOLDINGS = [
    {"name": "Apple Inc", "normalized_name": "apple", "isin": "US0378331005", "weight": 0.09},
    {"name": "NVIDIA Corp", "normalized_name": "nvidia", "isin": "US67066G1040", "weight": 0.08},
]

FUND_HOLDINGS = {"VOO": VOO_HOLDINGS, "QQQ": QQQ_HOLDINGS}


@pytest.fixture
def account(monkeypatch):
    """An account holding one stock plus two overlapping funds."""

    class _Adapter:
        def get_snapshot(self):
            return {
                "as_of": "2026-06-30",
                "cash": 1000.0,
                "total_portfolio_value": 10000.0,
                "holdings": [
                    {"ticker": "AAPL", "weight": 0.30},
                    {"ticker": "VOO", "weight": 0.40},
                    {"ticker": "QQQ", "weight": 0.20},
                ],
            }

    monkeypatch.setattr(true_exposure, "load_default_adapter", lambda: _Adapter())
    monkeypatch.setattr(
        true_exposure,
        "resolve_fund",
        lambda ticker: {"status": "ok"} if ticker.upper() in FUND_HOLDINGS else {"status": "not_a_fund"},
    )
    monkeypatch.setattr(
        true_exposure,
        "_identify_position",
        lambda ticker: {
            "ticker": ticker.upper(),
            "isin": "US0378331005" if ticker.upper() == "AAPL" else None,
            "name": "Apple Inc." if ticker.upper() == "AAPL" else ticker.upper(),
            "normalized_name": "apple" if ticker.upper() == "AAPL" else ticker.lower(),
        },
    )

    def fake_holdings(ticker):
        symbol = ticker.upper()
        return {
            "status": "ok",
            "ticker": symbol,
            "fund": {"series_name": f"{symbol} TEST FUND"},
            "holdings": FUND_HOLDINGS[symbol],
            "holdings_count": len(FUND_HOLDINGS[symbol]),
            "as_of": "2026-03-31",
            "source_url": f"https://example.test/{symbol}.xml",
        }

    monkeypatch.setattr(true_exposure, "fetch_fund_holdings", fake_holdings)


def _find(result, key):
    return next(r for r in result["top_exposures"] if r["key"] == key)


class TestLookThrough:
    def test_a_funds_weight_is_multiplied_through_not_counted_at_face_value(self, account):
        result = true_exposure.compute_true_exposure()
        nvidia = _find(result, "nvidia")
        # 0.40 of the account in VOO, which is 0.06 Nvidia -> 0.024
        # 0.20 of the account in QQQ, which is 0.08 Nvidia -> 0.016
        assert nvidia["look_through_weight"] == pytest.approx(0.04)

    def test_an_issuer_held_directly_and_via_funds_is_one_row_not_two(self, account):
        result = true_exposure.compute_true_exposure()
        rows = [r for r in result["top_exposures"] if r["key"] in ("AAPL", "apple")]
        assert len(rows) == 1
        apple = rows[0]
        assert apple["held_directly"] is True
        assert apple["direct_weight"] == pytest.approx(0.30)
        # 0.40 * 0.07 + 0.20 * 0.09 = 0.046
        assert apple["look_through_weight"] == pytest.approx(0.046)
        assert apple["total_weight"] == pytest.approx(0.346)

    def test_an_issuer_owned_only_through_funds_is_surfaced(self, account):
        """The whole point: this exposure appears nowhere in a positions list."""
        result = true_exposure.compute_true_exposure()
        nvidia = _find(result, "nvidia")
        assert nvidia["held_directly"] is False
        assert nvidia["direct_weight"] == 0.0
        assert {v["fund"] for v in nvidia["via_funds"]} == {"VOO", "QQQ"}
        assert any(h["key"] == "nvidia" for h in result["hidden_concentration"])

    def test_exposures_are_ranked_by_total_weight(self, account):
        result = true_exposure.compute_true_exposure()
        weights = [r["total_weight"] for r in result["top_exposures"]]
        assert weights == sorted(weights, reverse=True)

    def test_top_n_limits_the_rows_returned(self, account):
        assert len(true_exposure.compute_true_exposure(top_n=1)["top_exposures"]) == 1


class TestHonesty:
    def test_a_fund_that_cannot_be_read_keeps_its_weight_and_is_named(self, account, monkeypatch):
        """A dropped fund would understate concentration — it must be reported."""
        monkeypatch.setattr(
            true_exposure,
            "fetch_fund_holdings",
            lambda ticker: {"status": "series_not_found", "ticker": ticker, "reason": "no series"},
        )
        result = true_exposure.compute_true_exposure()
        unread = {f["ticker"]: f for f in result["funds_not_looked_through"]}
        assert set(unread) == {"VOO", "QQQ"}
        assert unread["VOO"]["weight_in_account"] == pytest.approx(0.40)
        assert unread["VOO"]["reason"] == "no series"
        assert result["funds_looked_through"] == []

    def test_each_looked_through_fund_carries_its_as_of_and_source(self, account):
        result = true_exposure.compute_true_exposure()
        assert result["funds_looked_through"]
        for fund in result["funds_looked_through"]:
            assert fund["holdings_as_of"] == "2026-03-31"
            assert fund["source_url"].startswith("https://")
        assert "2026-03-31" not in (result["staleness_warning"] or "")
        assert "never describe this as current exposure" in result["staleness_warning"]

    def test_result_is_stamped_computed_with_its_inputs_named(self, account):
        result = true_exposure.compute_true_exposure()
        assert result["source"] == "computed"
        assert "no vendor figures" in result["basis"]
        assert result["inputs_used"]["direct_positions"] == 1
        assert result["inputs_used"]["fund_positions"] == 2

    def test_it_disclaims_being_a_risk_model(self, account):
        """Weight arithmetic must not be read as a correlation model."""
        result = true_exposure.compute_true_exposure()
        assert "not a risk or correlation model" in result["not_a_risk_model"]

    def test_an_unreachable_fund_map_refuses_rather_than_guessing(self, account, monkeypatch):
        def boom(ticker):
            raise true_exposure.FundLookupError("map down")

        monkeypatch.setattr(true_exposure, "resolve_fund", boom)
        result = true_exposure.compute_true_exposure()
        assert result["status"] == "fund_map_unavailable"
        assert "overstate diversification" in result["reason"]
