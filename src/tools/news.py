"""Recent press coverage for a ticker — a citation source, not a score.

Every other evidence source in this project answers "what is true": the
filing tools compute ratios from audited disclosures, the quote tools report
what the market last paid. None of them answer "what just happened." A
guidance cut, a CEO departure, or a regulatory action from last week is
invisible to a research note whose newest evidence is a ten-month-old 10-K.

This module fills that gap in the one way that doesn't compromise the rest
of the project: **headlines enter as citable evidence, never as a number.**
A publisher, a headline, a URL, and a timestamp are exactly as citable as a
10-K section heading, and they carry their own provenance — the reader can
see who said it and when.

## Why there is no sentiment score here

The obvious feature request is ``sentiment: 0.72``. It is deliberately
absent, and should stay absent. Every number this project states must trace
back to a named deterministic tool (see CLAUDE.md); a polarity score traces
back to nothing but a model's judgment, dressed in a decimal point that
makes it look computed. It would be the least trustworthy figure in the
codebase while looking like the most precise.

The useful half of "sentiment" survives without it. A research note can say
"three of the five stories this week lead on the margin guidance cut
(Reuters, 2026-08-01, <url>)" — that characterizes tone, and every word of
it is checkable. Averaging those five stories into 0.72 would have destroyed
exactly the information that made the sentence worth trusting.

## Evidence rank

A filing outranks a headline. Press coverage can raise a risk, add
timeliness, or open a question; it can never be the sole basis for an
investment view, never contradict a filing-derived figure, and never supply
a number to a note. Yahoo's feed mixes wire services with low-quality
aggregators, which is precisely why every article carries its publisher —
the reader discounts the source themselves, rather than having it silently
averaged in.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import yfinance as yf

BASIS = (
    "Press coverage retrieved from Yahoo Finance. These are journalists' claims, "
    "not company disclosures — a filing outranks a headline. Cite by publisher, "
    "headline, and date; never state a figure that appears only in a news story "
    "as though a tool computed it."
)


def _extract(item: Any) -> dict[str, Any] | None:
    """Map one raw feed item to our shape, or None if it isn't citable.

    yfinance's news payload is undocumented and has changed shape before, so
    every access here is defensive. An item without a title or a URL is
    dropped rather than emitted with nulls: a citation without a URL is not a
    citation, and a half-filled one invites a note to cite something it
    can't point at.
    """
    if not isinstance(item, dict):
        return None

    content = item.get("content")
    if not isinstance(content, dict):
        return None

    title = content.get("title")
    if not title:
        return None

    url_block = content.get("canonicalUrl") or content.get("clickThroughUrl") or {}
    url = url_block.get("url") if isinstance(url_block, dict) else None
    if not url:
        return None

    provider = content.get("provider") or {}
    publisher = provider.get("displayName") if isinstance(provider, dict) else None

    return {
        "title": title,
        "publisher": publisher,
        "url": url,
        "published": content.get("pubDate") or content.get("displayTime"),
        "summary": content.get("summary") or "",
        "content_type": content.get("contentType"),
    }


def fetch_recent_news(ticker: str, limit: int = 8) -> dict[str, Any]:
    """Return recent press coverage for a ticker, newest first.

    Each article carries the publisher, headline, URL, and publish time
    needed to cite it. Nothing here is scored or interpreted.
    """
    symbol = ticker.upper()
    as_of = datetime.now(timezone.utc).isoformat(timespec="seconds")

    try:
        raw = yf.Ticker(symbol).news
    except Exception as exc:
        return {"ticker": symbol, "as_of": as_of, "error": f"Could not fetch news: {exc}", "articles": []}

    if not isinstance(raw, list):
        raw = []

    articles = [a for a in (_extract(item) for item in raw) if a is not None]
    # Missing timestamps sort last rather than crashing the comparison.
    articles.sort(key=lambda a: a["published"] or "", reverse=True)
    articles = articles[: max(0, limit)]

    result: dict[str, Any] = {
        "ticker": symbol,
        "as_of": as_of,
        "count": len(articles),
        "basis": BASIS,
        "articles": articles,
    }
    if not articles:
        result["note"] = "No recent news returned for this ticker."
    return result
