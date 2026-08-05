"""Scoring stated views against realized price moves."""

from datetime import datetime, timedelta, timezone

from src.state.track_record import score_views

NOW = datetime(2026, 8, 5, tzinfo=timezone.utc)


def _view(rating, price, days_ago, ticker="NVDA", run_id="r1"):
    ts = (NOW - timedelta(days=days_ago)).isoformat().replace("+00:00", "Z")
    return {
        "run_id": run_id,
        "timestamp": ts,
        "note_path": f"../notes/{run_id}.md",
        "view": {
            "rating": rating,
            "tickers": [ticker],
            "view_price": {ticker: price},
            "change_my_mind": [],
        },
    }


def test_bullish_view_that_rose_is_correct():
    result = score_views([_view("bullish", 100.0, 30)], {"NVDA": 120.0}, NOW)
    row = result["rows"][0]
    assert row["status"] == "correct"
    assert row["pct_change"] == 20.0
    assert result["summary"] == {"total": 1, "resolved": 1, "correct": 1}


def test_bearish_view_that_rose_is_incorrect():
    result = score_views([_view("bearish", 100.0, 30)], {"NVDA": 120.0}, NOW)
    assert result["rows"][0]["status"] == "incorrect"
    assert result["summary"]["correct"] == 0


def test_bearish_view_that_fell_is_correct():
    result = score_views([_view("bearish", 100.0, 30)], {"NVDA": 80.0}, NOW)
    assert result["rows"][0]["status"] == "correct"
    assert result["rows"][0]["pct_change"] == -20.0


def test_recent_view_is_pending_even_if_it_moved():
    result = score_views([_view("bullish", 100.0, 2)], {"NVDA": 200.0}, NOW)
    assert result["rows"][0]["status"] == "pending"
    assert result["summary"] == {"total": 1, "resolved": 0, "correct": 0}


def test_neutral_view_within_five_percent_is_correct():
    result = score_views([_view("neutral", 100.0, 30)], {"NVDA": 103.0}, NOW)
    assert result["rows"][0]["status"] == "correct"


def test_neutral_view_that_ran_is_incorrect():
    result = score_views([_view("neutral", 100.0, 30)], {"NVDA": 140.0}, NOW)
    assert result["rows"][0]["status"] == "incorrect"


def test_missing_current_price_is_pending():
    result = score_views([_view("bullish", 100.0, 30)], {}, NOW)
    assert result["rows"][0]["status"] == "pending"
    assert result["rows"][0]["pct_change"] is None


def test_view_without_recorded_price_is_skipped():
    v = _view("bullish", 100.0, 30)
    v["view"]["view_price"] = {}
    assert score_views([v], {"NVDA": 120.0}, NOW)["rows"] == []


def test_view_without_timestamp_is_skipped():
    v = _view("bullish", 100.0, 30)
    v["timestamp"] = None
    assert score_views([v], {"NVDA": 120.0}, NOW)["rows"] == []


def test_unrecognised_rating_is_skipped():
    v = _view("very bullish", 100.0, 30)
    assert score_views([v], {"NVDA": 120.0}, NOW)["rows"] == []


def test_multi_ticker_view_yields_one_row_per_ticker():
    v = _view("bullish", 100.0, 30)
    v["view"]["view_price"] = {"NVDA": 100.0, "AAPL": 200.0}
    result = score_views(v and [v], {"NVDA": 110.0, "AAPL": 180.0}, NOW)
    assert {r["ticker"] for r in result["rows"]} == {"NVDA", "AAPL"}
    assert result["summary"] == {"total": 2, "resolved": 2, "correct": 1}
