"""Deterministic metrics engine: correct math on fixtures, None over guessing."""

import pytest

from src.tools.metrics_engine import compute_concentration, compute_ratios, compute_sector_weights


FIXTURE = {
    "revenue": 1000.0,
    "cogs": 400.0,
    "operating_income": 300.0,
    "net_income": 200.0,
    "total_debt": 500.0,
    "cash_and_equivalents": 100.0,
    "ebitda": 350.0,
    "interest_expense": 50.0,
    "current_assets": 600.0,
    "current_liabilities": 300.0,
    "market_cap": 4000.0,
    "eps": 2.0,
    "prior_year_revenue": 800.0,
    "prior_year_eps": 1.5,
}


def test_gross_margin_is_correct():
    result = compute_ratios(FIXTURE)
    assert result["ratios"]["gross_margin"] == pytest.approx((1000 - 400) / 1000)


def test_net_margin_is_correct():
    result = compute_ratios(FIXTURE)
    assert result["ratios"]["net_margin"] == pytest.approx(200 / 1000)


def test_net_debt_to_ebitda_is_correct():
    result = compute_ratios(FIXTURE)
    # net_debt = 500 - 100 = 400; 400 / 350
    assert result["ratios"]["net_debt_to_ebitda"] == pytest.approx(400 / 350)


def test_revenue_growth_is_correct():
    result = compute_ratios(FIXTURE)
    assert result["ratios"]["revenue_growth_yoy"] == pytest.approx((1000 - 800) / 800)


def test_pe_ratio_is_correct():
    result = compute_ratios(FIXTURE)
    assert result["ratios"]["pe_ratio"] == pytest.approx(4000 / 200)


def test_missing_denominator_returns_none_not_a_guess():
    fixture = dict(FIXTURE)
    fixture["ebitda"] = 0
    result = compute_ratios(fixture)
    assert result["ratios"]["net_debt_to_ebitda"] is None


def test_missing_input_returns_none_not_a_guess():
    fixture = dict(FIXTURE)
    del fixture["interest_expense"]
    result = compute_ratios(fixture)
    assert result["ratios"]["interest_coverage"] is None


def test_inputs_used_are_returned_for_traceability():
    result = compute_ratios(FIXTURE)
    assert result["inputs_used"]["revenue"] == 1000.0
    assert result["inputs_used"]["net_debt"] == 400.0


def test_concentration_hhi_single_position_is_maximal():
    holdings = [{"ticker": "AAPL", "market_value": 1000.0}]
    result = compute_concentration(holdings)
    assert result["hhi"] == pytest.approx(10000.0)
    assert result["top_position_weight"] == pytest.approx(1.0)


def test_concentration_hhi_two_equal_positions():
    holdings = [
        {"ticker": "AAPL", "market_value": 500.0},
        {"ticker": "MSFT", "market_value": 500.0},
    ]
    result = compute_concentration(holdings)
    assert result["hhi"] == pytest.approx(5000.0)
    assert result["top_position_weight"] == pytest.approx(0.5)


def test_concentration_zero_value_returns_none_not_a_guess():
    result = compute_concentration([])
    assert result["hhi"] is None


def test_sector_weights_sum_to_one():
    holdings = [
        {"ticker": "AAPL", "sector": "Technology", "market_value": 300.0},
        {"ticker": "XOM", "sector": "Energy", "market_value": 700.0},
    ]
    weights = compute_sector_weights(holdings)
    assert weights["Technology"] == pytest.approx(0.3)
    assert weights["Energy"] == pytest.approx(0.7)
    assert sum(weights.values()) == pytest.approx(1.0)
