"""Read-only MCP server for the investment research copilot.

Exposes eight tools, all annotated read-only/non-destructive. Six operate
in the closed local sandbox (mock portfolio + local filing corpus); two
reach out to the public SEC EDGAR APIs and are annotated openWorldHint=True
so a client can see they touch the network, while still being marked
read-only/non-destructive since they only ever GET public filing data.

All real logic lives in ``src/tool_router.py``, shared with the FastAPI
backend (``backend/app.py``) used by the web/Telegram frontends — this file
is only the MCP surface.
"""

from typing import Any

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

from src import tool_router

mcp = FastMCP("invest-research-copilot")

READ_ONLY = ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=False, idempotentHint=True)
READ_ONLY_LIVE = ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=True, idempotentHint=False)


@mcp.tool(annotations=READ_ONLY)
def get_portfolio_snapshot() -> dict[str, Any]:
    """Return the full mock portfolio: cash, holdings with weights, watchlist.

    Read-only. Never places, modifies, or cancels trades.
    """
    return tool_router.get_portfolio_snapshot()


@mcp.tool(annotations=READ_ONLY)
def get_holding_detail(ticker: str) -> dict[str, Any] | None:
    """Return detail for one held ticker, or null if it isn't held.

    Read-only. Never places, modifies, or cancels trades.
    """
    return tool_router.get_holding_detail(ticker)


@mcp.tool(annotations=READ_ONLY)
def compute_metrics(ticker: str) -> dict[str, Any]:
    """Compute deterministic quality/leverage/valuation ratios for a ticker.

    All numbers come from the local filing corpus's fundamentals block via
    pure arithmetic in metrics_engine — nothing here is estimated. Recorded
    to the session ledger so a later question can cite this exact result.
    """
    return tool_router.compute_metrics(ticker)


@mcp.tool(annotations=READ_ONLY)
def search_filings(query: str, ticker: str | None = None, top_k: int = 3) -> list[dict[str, Any]]:
    """Search the local filing corpus; every hit carries a citation.

    Returns passages with ticker, section, source_url — use these for any
    qualitative claim in a research note.
    """
    return tool_router.search_filings(query, ticker=ticker, top_k=top_k)


@mcp.tool(annotations=READ_ONLY)
def compare_peers(ticker: str, peers: list[str]) -> dict[str, Any]:
    """Build a metrics table for ticker vs named peers, from local fundamentals.

    Peers not present in the local corpus are listed under 'missing', never
    silently guessed.
    """
    return tool_router.compare_peers(ticker, peers)


@mcp.tool(annotations=READ_ONLY)
def get_recent_research(n: int = 5) -> list[dict[str, Any]]:
    """Return the n most recent research runs from the session ledger.

    Use this to answer follow-up questions ("compare that to what we found
    for MSFT") from prior provenance instead of recomputing from scratch.
    """
    return tool_router.get_recent_research(n=n)


@mcp.tool(annotations=READ_ONLY_LIVE)
def fetch_live_fundamentals(ticker: str) -> dict[str, Any]:
    """Compute deterministic ratios from a company's real, live SEC XBRL filings.

    Use this for a ticker not in the local filing corpus. Every input comes
    directly from a value SEC's XBRL API reports for a specific US-GAAP tag
    on the latest annual (10-K) period — nothing is estimated. Fields the
    company doesn't tag (or that require live market data, like P/E) come
    back as null rather than a guess. Read-only: only ever performs GET
    requests against SEC's public data endpoints.
    """
    return tool_router.fetch_live_fundamentals(ticker)


@mcp.tool(annotations=READ_ONLY_LIVE)
def search_live_filings(ticker: str, query: str, top_k: int = 3) -> dict[str, Any]:
    """Search the actual text of a company's latest 10-K, fetched from SEC EDGAR.

    Use this for a ticker not in the local filing corpus. Every result
    carries the real filing's source URL as its citation. Read-only: only
    ever performs GET requests against SEC's public data endpoints.
    """
    return tool_router.search_live_filings(ticker, query, top_k=top_k)


if __name__ == "__main__":
    mcp.run(transport="stdio")
