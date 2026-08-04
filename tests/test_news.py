"""Tests for the news tool's citation promise — and its missing score.

Two things have to hold. First, every article this tool emits must be
citable: if it lacks a title or a URL it must be dropped, not passed through
with nulls, because a half-filled citation invites a note to cite something
it can't point at. Second, the payload shape is an undocumented third-party
feed that has changed before, so malformed input must degrade to "no
articles" rather than raise.

The last test is the odd one: it asserts the *absence* of a sentiment score.
That's a design decision (see the module docstring in src/tools/news.py), and
this is what stops it from being quietly undone later.
"""

from __future__ import annotations

import re

import pytest

from src.tools import news


def _item(title="A headline", url="https://example.com/a", pub="2026-08-04T16:00:00Z", publisher="Reuters"):
    return {
        "content": {
            "title": title,
            "summary": "Some summary.",
            "pubDate": pub,
            "contentType": "STORY",
            "provider": {"displayName": publisher},
            "canonicalUrl": {"url": url},
        }
    }


class _FakeTicker:
    """Stands in for yf.Ticker; ``news`` may be a payload or an exception."""

    def __init__(self, payload):
        self._payload = payload

    @property
    def news(self):
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload


@pytest.fixture
def feed(monkeypatch):
    def _set(payload):
        monkeypatch.setattr(news.yf, "Ticker", lambda symbol: _FakeTicker(payload))

    return _set


def test_maps_fields_and_sorts_newest_first(feed):
    feed([
        _item(title="Older", url="https://example.com/old", pub="2026-08-01T09:00:00Z"),
        _item(title="Newer", url="https://example.com/new", pub="2026-08-04T09:00:00Z"),
    ])
    result = news.fetch_recent_news("nke")

    assert result["ticker"] == "NKE"
    assert result["count"] == 2
    assert [a["title"] for a in result["articles"]] == ["Newer", "Older"]

    first = result["articles"][0]
    assert first["publisher"] == "Reuters"
    assert first["url"] == "https://example.com/new"
    assert first["published"] == "2026-08-04T09:00:00Z"
    assert first["content_type"] == "STORY"


def test_limit_is_respected(feed):
    feed([_item(url=f"https://example.com/{i}", pub=f"2026-08-0{i}T09:00:00Z") for i in range(1, 6)])
    assert news.fetch_recent_news("AAPL", limit=2)["count"] == 2


def test_uncitable_items_are_dropped_not_nulled(feed):
    no_url = _item(title="No link")
    del no_url["content"]["canonicalUrl"]
    no_title = _item(title="", url="https://example.com/untitled")

    feed([no_url, no_title, _item(title="Good", url="https://example.com/good")])
    articles = news.fetch_recent_news("AAPL")["articles"]

    assert [a["title"] for a in articles] == ["Good"]
    assert all(a["url"] and a["title"] for a in articles)


def test_clickthrough_url_is_accepted_when_canonical_is_absent(feed):
    item = _item()
    del item["content"]["canonicalUrl"]
    item["content"]["clickThroughUrl"] = {"url": "https://example.com/click"}

    feed([item])
    assert news.fetch_recent_news("AAPL")["articles"][0]["url"] == "https://example.com/click"


def test_unexpected_shapes_degrade_to_empty(feed):
    feed([{"no_content_key": True}, "a bare string", None, {"content": "not a dict"}])
    result = news.fetch_recent_news("AAPL")

    assert result["articles"] == []
    assert result["count"] == 0
    assert "note" in result


def test_empty_feed_is_a_note_not_an_error(feed):
    feed([])
    result = news.fetch_recent_news("AAPL")

    assert result["count"] == 0
    assert "error" not in result
    assert result["note"] == "No recent news returned for this ticker."


def test_fetch_failure_returns_an_error_not_a_traceback(feed):
    feed(RuntimeError("network down"))
    result = news.fetch_recent_news("AAPL")

    assert "network down" in result["error"]
    assert result["articles"] == []


def test_no_sentiment_score_is_ever_returned(feed):
    """Encodes the design decision so it can't be reintroduced by accident."""
    feed([_item()])
    result = news.fetch_recent_news("AAPL")

    banned = re.compile(r"sentiment|score|tone|polarity|bullish|bearish", re.I)

    def walk(node, path="result"):
        if isinstance(node, dict):
            for key, value in node.items():
                assert not banned.search(str(key)), f"banned key {path}.{key}"
                # `basis` is prose explaining the boundary; it may say the words.
                if key != "basis":
                    walk(value, f"{path}.{key}")
        elif isinstance(node, list):
            for i, value in enumerate(node):
                walk(value, f"{path}[{i}]")

    walk(result)
