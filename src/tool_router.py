"""Shared tool implementations + Anthropic-format schemas.

This is the single place the eight read-only research tools are
implemented. ``src/mcp_server.py`` wraps these functions for Claude Code
via MCP; ``backend/app.py`` calls them directly inside an Anthropic API
tool-use loop for the web/Telegram frontends. Keeping one implementation
means the safety properties (read-only, no fabricated numbers, session
ledger recording) hold identically no matter which interface is asking.
"""

from __future__ import annotations

from typing import Any, Callable

from src.obs.trace import traced
from src.state.metrics_cache import compute_ratios_cached
from src.state.session_store import get_default_store
from src.tools.edgar_client import EdgarLookupError
from src.tools.edgar_filings import search_live_filing as _search_live_filing
from src.tools.edgar_fundamentals import fetch_live_fundamentals as _fetch_live_fundamentals
from src.tools.filings_search import search_filings as _search_filings
from src.tools.fundamentals import get_fundamentals
from src.tools.mock_portfolio import load_default_adapter
from src.tools.peer_compare import compare_peers as _compare_peers


@traced("get_portfolio_snapshot")
def get_portfolio_snapshot() -> dict[str, Any]:
    return load_default_adapter().get_snapshot()


@traced("get_holding_detail")
def get_holding_detail(ticker: str) -> dict[str, Any] | None:
    return load_default_adapter().get_holding(ticker)


@traced("compute_metrics")
def compute_metrics(ticker: str) -> dict[str, Any]:
    fundamentals = get_fundamentals(ticker)
    if fundamentals is None:
        return {"error": f"No fundamentals available for {ticker.upper()} in the local filing corpus."}

    result, cache_hit = compute_ratios_cached(ticker, fundamentals.get("fiscal_year"), fundamentals)
    store = get_default_store()
    try:
        store.record_tool_call("compute_metrics", {"ticker": ticker.upper()}, {"cache_hit": cache_hit})
    except RuntimeError:
        pass  # no active run — fine to skip
    return {**result, "cache_hit": cache_hit}


@traced("search_filings")
def search_filings(query: str, ticker: str | None = None, top_k: int = 3) -> list[dict[str, Any]]:
    results = _search_filings(query, top_k=top_k, ticker=ticker)
    store = get_default_store()
    for hit in results:
        try:
            store.record_citation(hit["ticker"], hit["section"], hit["source_url"])
        except RuntimeError:
            break  # no active run — fine to skip the rest too
    return results


@traced("compare_peers")
def compare_peers(ticker: str, peers: list[str]) -> dict[str, Any]:
    return _compare_peers(ticker, peers)


@traced("get_recent_research")
def get_recent_research(n: int = 5) -> list[dict[str, Any]]:
    return get_default_store().recent_runs(n=n)


@traced("fetch_live_fundamentals")
def fetch_live_fundamentals(ticker: str) -> dict[str, Any]:
    try:
        fundamentals = _fetch_live_fundamentals(ticker)
    except EdgarLookupError as exc:
        return {"error": str(exc)}

    result, cache_hit = compute_ratios_cached(ticker, fundamentals.get("fiscal_year"), fundamentals)
    store = get_default_store()
    try:
        store.record_tool_call("fetch_live_fundamentals", {"ticker": ticker.upper()}, {"cache_hit": cache_hit})
    except RuntimeError:
        pass
    return {**result, "cache_hit": cache_hit, "company": fundamentals.get("company"), "source": fundamentals.get("source")}


@traced("search_live_filings")
def search_live_filings(ticker: str, query: str, top_k: int = 3) -> dict[str, Any]:
    try:
        result = _search_live_filing(ticker, query, top_k=top_k)
    except EdgarLookupError as exc:
        return {"error": str(exc)}

    store = get_default_store()
    filing = result.get("filing", {})
    for _ in result.get("results", []):
        try:
            store.record_citation(ticker.upper(), "live 10-K excerpt", filing.get("url", ""))
        except RuntimeError:
            break
    return result


TOOL_FUNCTIONS: dict[str, Callable[..., Any]] = {
    "get_portfolio_snapshot": get_portfolio_snapshot,
    "get_holding_detail": get_holding_detail,
    "compute_metrics": compute_metrics,
    "search_filings": search_filings,
    "compare_peers": compare_peers,
    "get_recent_research": get_recent_research,
    "fetch_live_fundamentals": fetch_live_fundamentals,
    "search_live_filings": search_live_filings,
}

# Anthropic Messages API tool-use schemas. input_schema follows JSON Schema.
TOOL_SCHEMAS: list[dict[str, Any]] = [
    {
        "name": "get_portfolio_snapshot",
        "description": "Return the full mock portfolio: cash, holdings with weights and unrealized P/L, watchlist. Read-only.",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "get_holding_detail",
        "description": "Return detail for one held ticker, or null if it isn't held. Read-only.",
        "input_schema": {
            "type": "object",
            "properties": {"ticker": {"type": "string"}},
            "required": ["ticker"],
        },
    },
    {
        "name": "compute_metrics",
        "description": (
            "Compute deterministic quality/leverage/valuation ratios for a ticker in the local "
            "filing corpus (AAPL, MSFT, NKE). Nothing is estimated. Use fetch_live_fundamentals "
            "for any other ticker."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"ticker": {"type": "string"}},
            "required": ["ticker"],
        },
    },
    {
        "name": "search_filings",
        "description": (
            "Search the local filing corpus (AAPL, MSFT, NKE); every hit carries a citation "
            "(ticker, section, source_url). Use for qualitative claims about local-corpus tickers."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "ticker": {"type": "string", "description": "Optional: scope to one ticker."},
                "top_k": {"type": "integer", "default": 3},
            },
            "required": ["query"],
        },
    },
    {
        "name": "compare_peers",
        "description": "Build a metrics table for a ticker vs named peers, using local filing corpus fundamentals only.",
        "input_schema": {
            "type": "object",
            "properties": {
                "ticker": {"type": "string"},
                "peers": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["ticker", "peers"],
        },
    },
    {
        "name": "get_recent_research",
        "description": "Return the n most recent research runs from the session ledger, for follow-up questions.",
        "input_schema": {
            "type": "object",
            "properties": {"n": {"type": "integer", "default": 5}},
            "required": [],
        },
    },
    {
        "name": "fetch_live_fundamentals",
        "description": (
            "Compute deterministic ratios from a company's real, live SEC XBRL filings. Use for "
            "any ticker NOT in the local corpus (AAPL, MSFT, NKE). Fields the company doesn't tag "
            "(EBITDA, market cap, and anything derived from them) come back null, never estimated."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"ticker": {"type": "string"}},
            "required": ["ticker"],
        },
    },
    {
        "name": "search_live_filings",
        "description": (
            "Search the actual text of a company's latest 10-K, fetched live from SEC EDGAR. Use "
            "for any ticker NOT in the local corpus. Every result carries the real filing URL."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "ticker": {"type": "string"},
                "query": {"type": "string"},
                "top_k": {"type": "integer", "default": 3},
            },
            "required": ["ticker", "query"],
        },
    },
]


def call_tool(name: str, tool_input: dict[str, Any]) -> Any:
    func = TOOL_FUNCTIONS.get(name)
    if func is None:
        return {"error": f"Unknown tool '{name}'."}
    return func(**tool_input)
