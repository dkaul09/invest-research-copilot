"""Live quotes/price history: graceful degradation, no fabrication.

Mocks yfinance so these run deterministically offline, and to prove the
error path (unknown ticker, missing data) never crashes or returns a
made-up number — it returns an explicit error field instead.
"""

from __future__ import annotations

import pandas as pd
import pytest

from src.tools import quotes


class FakeFastInfo:
    def __init__(self, last_price, previous_close):
        self.last_price = last_price
        self.previous_close = previous_close


class FakeTicker:
    def __init__(self, ticker):
        self.ticker = ticker

    @property
    def fast_info(self):
        if self.ticker == "BADTICKER":
            raise KeyError("exchangeTimezoneName")
        return FakeFastInfo(last_price=150.0, previous_close=145.0)

    def history(self, period="3mo"):
        if self.ticker == "BADTICKER":
            return pd.DataFrame()
        return pd.DataFrame(
            {"Close": [140.0, 145.0, 150.0]},
            index=pd.to_datetime(["2026-01-01", "2026-01-02", "2026-01-03"]),
        )


@pytest.fixture(autouse=True)
def patch_yfinance(monkeypatch):
    monkeypatch.setattr(quotes.yf, "Ticker", FakeTicker)


def test_get_quote_returns_price_and_change():
    result = quotes.get_quote("AAPL")
    assert result["price"] == 150.0
    assert result["previous_close"] == 145.0
    assert result["change"] == pytest.approx(5.0)
    assert result["change_pct"] == pytest.approx(5.0 / 145.0, rel=1e-3)


def test_get_quote_bad_ticker_returns_error_not_fabricated_price():
    result = quotes.get_quote("BADTICKER")
    assert "error" in result
    assert "price" not in result


def test_get_price_history_returns_points():
    result = quotes.get_price_history("AAPL", period="1mo")
    assert result["points"] == [
        {"date": "2026-01-01", "close": 140.0},
        {"date": "2026-01-02", "close": 145.0},
        {"date": "2026-01-03", "close": 150.0},
    ]


def test_get_price_history_empty_returns_error_not_fabricated_points():
    result = quotes.get_price_history("BADTICKER")
    assert result["points"] == []
    assert "error" in result
