"""MCP server for the investment research copilot.

Exposes twenty-two tools. Eighteen are read-only (account/filing data never
mutated); four (`add_to_watchlist`, `remove_from_watchlist`,
`add_price_alert`, `remove_price_alert`) are the deliberate exceptions — a personal watchlist is a tracking list, not
account or trade data, so it's fine for them to be genuinely writable, and
neither can act on anything. Ten tools reach public network APIs (SEC
EDGAR, live quote data, or the news feed) and are
annotated openWorldHint=True so a client can see they touch the network.

The four fund tools (`get_fund_profile`, `search_fund_filings`,
`compare_funds`, `compute_fund_overlap`) exist because an ETF is not a
company: it files no 10-K and has no XBRL company facts, so the equity
tools structurally cannot answer a question about VOO or VXUS.

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
# The watchlist is a personal tracking list, not account or trade data — the
# only tools in this project that are intentionally not read-only.
WATCHLIST_WRITE = ToolAnnotations(readOnlyHint=False, destructiveHint=False, openWorldHint=False, idempotentHint=False)


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


@mcp.tool(annotations=READ_ONLY)
def get_watchlist() -> list[dict[str, Any]]:
    """Return the user's personal watchlist (tickers they're tracking, not held)."""
    return tool_router.get_watchlist()


@mcp.tool(annotations=WATCHLIST_WRITE)
def add_to_watchlist(ticker: str, sector: str = "") -> list[dict[str, Any]]:
    """Add a ticker to the personal watchlist.

    Not a trade — this is a tracking list, not account or brokerage data —
    so this is safe to call whenever the user asks to track/watch a ticker.
    """
    return tool_router.add_to_watchlist(ticker, sector=sector)


@mcp.tool(annotations=WATCHLIST_WRITE)
def remove_from_watchlist(ticker: str) -> list[dict[str, Any]]:
    """Remove a ticker from the personal watchlist."""
    return tool_router.remove_from_watchlist(ticker)


@mcp.tool(annotations=WATCHLIST_WRITE)
def add_price_alert(
    ticker: str, direction: str, pct: float, baseline: str = "prev_close"
) -> dict[str, Any]:
    """Record a price condition the user wants to be notified about later.

    Saves the condition only — nothing checks prices yet, so say plainly that
    delivery is not wired up. Not an execution path: this project cannot act
    on a price. ``direction`` is "down" or "up"; ``baseline`` is one of
    "prev_close", "7d", "30d", or "view_price" (the price when the user last
    recorded a view on this ticker).
    """
    return tool_router.add_price_alert(ticker, direction, pct, baseline=baseline)


@mcp.tool(annotations=READ_ONLY)
def list_price_alerts() -> dict[str, Any]:
    """List the user's saved price-watch conditions."""
    return tool_router.list_price_alerts()


@mcp.tool(annotations=WATCHLIST_WRITE)
def remove_price_alert(alert_id: str) -> dict[str, Any]:
    """Delete a saved price-watch condition by its id."""
    return tool_router.remove_price_alert(alert_id)


@mcp.tool(annotations=READ_ONLY_LIVE)
def get_quote(ticker: str) -> dict[str, Any]:
    """Get the latest live price, previous close, and day change for a ticker.

    This is market price data, not a financial ratio — never use it as an
    input to compute_metrics or state it as a computed metric.
    """
    return tool_router.get_quote(ticker)


@mcp.tool(annotations=READ_ONLY_LIVE)
def get_price_history(ticker: str, period: str = "3mo") -> dict[str, Any]:
    """Get historical daily closing prices for a ticker, for trend/chart display."""
    return tool_router.get_price_history(ticker, period=period)


@mcp.tool(annotations=READ_ONLY_LIVE)
def fetch_market_valuation(ticker: str) -> dict[str, Any]:
    """Compute P/E, market cap, and EV/EBITDA from a live price plus filing figures.

    Use when a question turns on valuation: fetch_live_fundamentals leaves
    those fields null by design, because a multiple can't be computed from a
    filing alone. Every result is market-derived and carries the price and
    as-of time it was computed at — report it that way, never as a filing
    fact. Multiples that can't be computed return null with a stated reason.
    Read-only.
    """
    return tool_router.fetch_market_valuation(ticker)


@mcp.tool(annotations=READ_ONLY_LIVE)
def fetch_recent_news(ticker: str, limit: int = 8) -> dict[str, Any]:
    """Get recent press coverage for a ticker: headline, publisher, URL, publish time.

    This is a citation source, not a number source. Cite an article by
    publisher and date; never state a figure that appears only in a news
    story as though a tool computed it. A filing outranks a headline — news
    can raise a risk, add timeliness, or open a question, but it can never be
    the sole basis for an investment view or contradict a filing-derived
    figure. There is deliberately no sentiment score: characterize tone in
    prose tied to specific cited articles. Read-only.
    """
    return tool_router.fetch_recent_news(ticker, limit=limit)


@mcp.tool(annotations=READ_ONLY_LIVE)
def get_fund_profile(ticker: str) -> dict[str, Any]:
    """Profile an index fund or ETF: expense ratio, net assets, holdings, sector mix.

    Use this for a fund (VOO, VXUS, QQQ) instead of compute_metrics or
    fetch_live_fundamentals, which structurally cannot work on one — a fund
    files no 10-K and has no XBRL company facts. Every field comes back as
    {value, source, as_of}: "vendor" is a Yahoo Finance summary, not a
    primary source. Fields only a prospectus can state (replication method,
    distribution policy, securities lending) return null pointing at
    search_fund_filings; tracking difference is permanently null because it
    requires index returns no free source provides. Never fill in a null
    from memory. Read-only.
    """
    return tool_router.get_fund_profile(ticker)


@mcp.tool(annotations=READ_ONLY_LIVE)
def search_fund_filings(ticker: str, query: str, top_k: int = 3) -> dict[str, Any]:
    """Search a fund's real SEC prospectus and annual report for cited passages.

    The citation source for any qualitative claim about a fund — objective,
    benchmark, replication, distribution policy, securities lending, risks.
    Reads the summary prospectus (497K), statutory prospectus (485BPOS), and
    annual report (N-CSR); each result carries the form, filing date, and
    source URL. These are trust-level documents covering many sibling funds,
    so confirm a passage names this specific fund before citing it.
    Read-only: GET requests against SEC's public endpoints only.
    """
    return tool_router.search_fund_filings(ticker, query, top_k=top_k)


@mcp.tool(annotations=READ_ONLY_LIVE)
def compare_funds(tickers: list[str]) -> dict[str, Any]:
    """Compare funds with the same mandate on cost, scale, turnover, and concentration.

    Vendor-sourced for speed across several funds; confirm the deciding
    figure against the prospectus with search_fund_filings. Tickers that
    aren't supported funds come back under 'unavailable' with a reason —
    report them as missing, never fill them in. If
    lowest_expense_ratio_tickers holds more than one ticker, those funds
    charge the same fee; say so rather than picking one. Read-only.
    """
    return tool_router.compare_funds(tickers)


@mcp.tool(annotations=READ_ONLY_LIVE)
def compute_fund_overlap(ticker: str) -> dict[str, Any]:
    """Compute how much of a fund the account already owns, from its N-PORT holdings.

    Answers "if I add this fund, what do I actually end up owning?" by
    intersecting account holdings with the fund's real filed holdings. Purely
    computed from the account fixture and a filing — nothing estimated.
    Holdings are as of the N-PORT reporting period end (a quarter-end, filed
    up to 60 days later): always state that date, and never describe the
    result as the fund's current holdings. Read-only.
    """
    return tool_router.compute_fund_overlap(ticker)


@mcp.tool(annotations=READ_ONLY_LIVE)
def compute_true_exposure(top_n: int = 15) -> dict[str, Any]:
    """Aggregate issuer-level exposure across the account, looking through held funds.

    Answers "am I actually diversified?" — a positions list shows tickers,
    but two broad funds plus a direct position can be the same handful of
    mega-cap issuers counted three times. Multiplies each held fund's account
    weight by each issuer's weight in that fund's real N-PORT holdings and
    adds directly held weight. Purely computed from the account fixture and
    one filing per fund — nothing estimated, and it is weight arithmetic, not
    a risk or correlation model. Each fund's holdings are as of its N-PORT
    period end (a quarter-end filed up to 60 days later): state those dates
    and never describe the result as current exposure. Read-only.
    """
    return tool_router.compute_true_exposure(top_n)


if __name__ == "__main__":
    mcp.run(transport="stdio")
