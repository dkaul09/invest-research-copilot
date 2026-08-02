"""Read-only MCP server for the investment research copilot.

Exposes exactly six tools, all annotated read-only/non-destructive/closed-world
so any MCP client can see at a glance that this server never mutates state
and never reaches outside the local mock data + filing corpus:

  - get_portfolio_snapshot   whole-account view: cash, holdings, watchlist
  - get_holding_detail       detail for one held ticker
  - compute_metrics          deterministic ratios for one ticker (cached)
  - search_filings           cited passages from the local filing corpus
  - compare_peers            side-by-side metric table vs named peers
  - get_recent_research      prior runs from the session ledger

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
from src.tools.filings_search import search_filings as _search_filings
from src.tools.fundamentals import get_fundamentals
from src.tools.mock_portfolio import load_default_adapter
from src.tools.peer_compare import compare_peers as _compare_peers

mcp = FastMCP("invest-research-copilot")

READ_ONLY = ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=False, idempotentHint=True)


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


if __name__ == "__main__":
    mcp.run(transport="stdio")
