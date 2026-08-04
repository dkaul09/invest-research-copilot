"""Tests for the metrics cache's invalidation promise.

The cache is only safe if it can never serve a result computed from
different inputs than the ones it was asked about. These tests pin that:
same inputs hit, changed inputs miss.
"""

from __future__ import annotations

from src.state import metrics_cache


FUNDAMENTALS = {
    "revenue": 215_938_000_000.0,
    "cogs": 62_500_000_000.0,
    "operating_income": 130_387_000_000.0,
    "ebitda": None,
    "total_debt": 8_468_000_000.0,
    "cash_and_equivalents": 10_605_000_000.0,
}


def _cache(tmp_path):
    metrics_cache._default_cache = metrics_cache.MetricsCache(tmp_path / "metrics_cache.json")
    return metrics_cache._default_cache


def test_identical_inputs_hit_the_cache(tmp_path):
    _cache(tmp_path)
    first, hit_first = metrics_cache.compute_ratios_cached("NVDA", 2026, FUNDAMENTALS)
    second, hit_second = metrics_cache.compute_ratios_cached("NVDA", 2026, FUNDAMENTALS)

    assert hit_first is False
    assert hit_second is True
    assert first == second


def test_changed_inputs_miss_even_at_the_same_ticker_and_year(tmp_path):
    """The regression this guards: a newly derived EBITDA must not be masked
    by a cached result that was computed when EBITDA was still None."""
    _cache(tmp_path)
    stale, _ = metrics_cache.compute_ratios_cached("NVDA", 2026, FUNDAMENTALS)
    assert stale["ratios"]["net_debt_to_ebitda"] is None

    with_ebitda = {**FUNDAMENTALS, "ebitda": 133_230_000_000.0}
    fresh, hit = metrics_cache.compute_ratios_cached("NVDA", 2026, with_ebitda)

    assert hit is False
    assert fresh["ratios"]["net_debt_to_ebitda"] is not None


def test_fingerprint_is_stable_regardless_of_key_order(tmp_path):
    reordered = dict(reversed(list(FUNDAMENTALS.items())))
    assert metrics_cache.fingerprint(FUNDAMENTALS) == metrics_cache.fingerprint(reordered)
