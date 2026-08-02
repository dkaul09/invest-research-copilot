"""Read-only MCP server for the investment research copilot.

Exposes eight tools, all annotated read-only/non-destructive. Six operate
in the closed local sandbox (mock portfolio + local filing corpus); two
reach out to the public SEC EDGAR APIs and are annotated openWorldHint=True
so a client can see they touch the network, while still being marked
read-only/non-destructive since they only ever GET public filing data:

  - get_portfolio_snapshot   whole-account view: cash, holdings, watchlist
  - get_holding_detail       detail for one held ticker
  - compute_metrics          deterministic ratios for one ticker (cached, local corpus)
  - search_filings           cited passages from the local filing corpus
  - compare_peers            side-by-side metric table vs named peers
  - get_recent_research      prior runs from the session ledger
  - fetch_live_fundamentals  deterministic ratios sourced from real SEC XBRL data
  - search_live_filings      cited passages from a company's actual latest 10-K

Each wrapper is intentionally thin: all real logic lives in ``src/tools/``.
This file's only job is the MCP surface, tracing, and (for compute_metrics)
recording to the session ledger.
"""

from typing import Any

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

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

mcp = FastMCP("invest-research-copilot")

READ_ONLY = ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=False, idempotentHint=True)
READ_ONLY_LIVE = ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=True, idempotentHint=False)


@mcp.tool(annotations=READ_ONLY)
@traced("get_portfolio_snapshot")
def get_portfolio_snapshot() -> dict[str, Any]:
    """Return the full mock portfolio: cash, holdings with weights, watchlist.

    Read-only. Never places, modifies, or cancels trades.
    """
    return load_default_adapter().get_snapshot()


@mcp.tool(annotations=READ_ONLY)
@traced("get_holding_detail")
def get_holding_detail(ticker: str) -> dict[str, Any] | None:
    """Return detail for one held ticker, or null if it isn't held.

    Read-only. Never places, modifies, or cancels trades.
    """
    return load_default_adapter().get_holding(ticker)


@mcp.tool(annotations=READ_ONLY)
@traced("compute_metrics")
def compute_metrics(ticker: str) -> dict[str, Any]:
    """Compute deterministic quality/leverage/valuation ratios for a ticker.

    All numbers come from the local filing corpus's fundamentals block via
    pure arithmetic in metrics_engine — nothing here is estimated. Recorded
    to the session ledger so a later question can cite this exact result.
    """
    fundamentals = get_fundamentals(ticker)
    if fundamentals is None:
        return {"error": f"No fundamentals available for {ticker.upper()} in the local filing corpus."}

    result, cache_hit = compute_ratios_cached(ticker, fundamentals.get("fiscal_year"), fundamentals)
    store = get_default_store()
    try:
        store.record_tool_call("compute_metrics", {"ticker": ticker.upper()}, {"cache_hit": cache_hit})
    except RuntimeError:
        pass  # no active run (e.g. tool called outside the skill workflow) — fine to skip
    return {**result, "cache_hit": cache_hit}


@mcp.tool(annotations=READ_ONLY)
@traced("search_filings")
def search_filings(query: str, ticker: str | None = None, top_k: int = 3) -> list[dict[str, Any]]:
    """Search the local filing corpus; every hit carries a citation.

    Returns passages with ticker, section, source_url — use these for any
    qualitative claim in a research note.
    """
    return _search_filings(query, top_k=top_k, ticker=ticker)


@mcp.tool(annotations=READ_ONLY)
@traced("compare_peers")
def compare_peers(ticker: str, peers: list[str]) -> dict[str, Any]:
    """Build a metrics table for ticker vs named peers, from local fundamentals.

    Peers not present in the local corpus are listed under 'missing', never
    silently guessed.
    """
    return _compare_peers(ticker, peers)


@mcp.tool(annotations=READ_ONLY)
@traced("get_recent_research")
def get_recent_research(n: int = 5) -> list[dict[str, Any]]:
    """Return the n most recent research runs from the session ledger.

    Use this to answer follow-up questions ("compare that to what we found
    for MSFT") from prior provenance instead of recomputing from scratch.
    """
    return get_default_store().recent_runs(n=n)


@mcp.tool(annotations=READ_ONLY_LIVE)
@traced("fetch_live_fundamentals")
def fetch_live_fundamentals(ticker: str) -> dict[str, Any]:
    """Compute deterministic ratios from a company's real, live SEC XBRL filings.

    Use this for a ticker not in the local filing corpus. Every input comes
    directly from a value SEC's XBRL API reports for a specific US-GAAP tag
    on the latest annual (10-K) period — nothing is estimated. Fields the
    company doesn't tag (or that require live market data, like P/E) come
    back as null rather than a guess. Read-only: only ever performs GET
    requests against SEC's public data endpoints.
    """
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


@mcp.tool(annotations=READ_ONLY_LIVE)
@traced("search_live_filings")
def search_live_filings(ticker: str, query: str, top_k: int = 3) -> dict[str, Any]:
    """Search the actual text of a company's latest 10-K, fetched from SEC EDGAR.

    Use this for a ticker not in the local filing corpus. Every result
    carries the real filing's source URL as its citation. Read-only: only
    ever performs GET requests against SEC's public data endpoints.
    """
    try:
        return _search_live_filing(ticker, query, top_k=top_k)
    except EdgarLookupError as exc:
        return {"error": str(exc)}


if __name__ == "__main__":
    mcp.run(transport="stdio")
