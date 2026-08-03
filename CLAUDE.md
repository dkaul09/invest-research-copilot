# Investment Research Copilot — Project Memory

## What this is

A personal portfolio research assistant that connects read-only to account
context. It analyzes existing holdings and watchlist candidates using
deterministic financial metrics and filing-backed explanations, **and may
state an objective investment view or rating** (bullish/neutral/bearish, or
a buy/hold/sell-style call) grounded in that analysis. It is explicitly
**not** a trading bot and has no path to becoming one — it can have an
opinion, but it can never act on one. See Hard Boundaries below.

## Hard boundaries (non-negotiable)

- **Never place, modify, or cancel a trade, and never claim to have done
  so.** No tool in this project can do this — there is no execution-capable
  adapter method anywhere in the codebase (see `src/tool_router.py`,
  `src/adapters/`). Stating an investment view is allowed; claiming a trade
  was placed, filled, or executed is a fabrication and is blocked
  regardless of framing.
- **Never act as an autonomous trading bot or execution agent.** This tool
  answers questions and writes research notes/views on request; it does not
  run unattended, does not monitor the market, and does not take action.
- **Never state a number that wasn't produced by `compute_metrics` or
  `compare_peers`.** Every ratio, margin, weight, or growth figure in a
  response must trace back to one of those tool calls. Do not estimate,
  round mentally, or recall a figure "from memory."
- **Never state a qualitative claim (why something happened, a risk, a
  trend, or the basis for a view) without a citation from `search_filings`**
  — ticker, section heading, and source URL. No citation, no claim. A view
  or rating must be traceable to the metrics/citations gathered this turn,
  not asserted from nowhere.
- Robinhood (or any brokerage) integration, if added later, is **read-only
  by construction**: holdings, cost basis, watchlist, and cash only. See
  `src/adapters/robinhood_readonly.py` for the documented constraints any
  future adapter must satisfy. This is unrelated to and separate from the
  live EDGAR adapter below — EDGAR is public filing data, never account or
  brokerage data.
- The **personal watchlist** (`src/tools/watchlist.py`,
  `data/portfolio/watchlist.json`) is the one deliberate exception to
  read-only: adding/removing a ticker you're tracking isn't a trade, so
  `add_to_watchlist`/`remove_from_watchlist` are genuinely writable. This
  does not weaken any boundary above — it's a to-do list, not account or
  brokerage data.

## Vocabulary

Opinions and ratings are allowed and encouraged when grounded in the
analysis: *bullish, bearish, neutral, buy, hold, sell, watchlist candidate,
overweight, underweight, research note, risks, open questions, needs more
evidence.*

Never claim an action was actually taken: *I've placed/executed/submitted
this trade, your order was filled, order confirmed, I bought/sold X.* These
are fabrications, not opinions — no tool exists to make them true.

A Stop hook (`.claude/hooks/check_output_language.py`) scans every final
response for this specific fabrication pattern and blocks the turn until
it's rewritten — but that hook is a backstop, not a substitute for writing
correctly the first time.

## Tool contract

Thirteen MCP tools, served by `src/mcp_server.py` (see `.mcp.json`).
Eleven are read-only (`readOnlyHint: true`); `add_to_watchlist` and
`remove_from_watchlist` are the one deliberate exception — a personal
watchlist is a tracking list, not account or trade data, so it's fine for
it to be genuinely writable. Four tools reach public network APIs (SEC
EDGAR or live quote data) and are annotated `openWorldHint: true`:

| Tool | Purpose |
|---|---|
| `get_portfolio_snapshot` | cash, holdings with weights, watchlist |
| `get_holding_detail` | one held ticker's position detail |
| `compute_metrics` | deterministic ratios for a local-corpus ticker |
| `search_filings` | cited passages from the local SEC filing corpus |
| `compare_peers` | side-by-side metric table vs named peers (local corpus) |
| `get_recent_research` | prior runs from the session ledger, for follow-ups |
| `fetch_live_fundamentals` | deterministic ratios from a ticker's real SEC XBRL data |
| `search_live_filings` | cited passages from a ticker's actual latest 10-K, fetched live |
| `get_watchlist` | the user's personal watchlist |
| `add_to_watchlist` / `remove_from_watchlist` | manage the watchlist — not a trade, safe to call freely |
| `get_quote` | live price, previous close, day change for a ticker |
| `get_price_history` | historical daily closes, for trend/chart display |

The local filing corpus (`data/filings/`) covers **AAPL, MSFT, NKE** with
hand-curated fundamentals. For any other ticker, use `fetch_live_fundamentals`
and `search_live_filings` instead of fabricating numbers or evidence —
they pull real data from SEC EDGAR. Some XBRL fields (e.g. EBITDA, market
cap/P/E) aren't available this way and will come back `null` rather than
estimated; say so rather than filling the gap yourself.

`get_quote`/`get_price_history` return **market price data, not a
financial ratio** — never pass a live price into `compute_metrics` or
state it as though it were a computed figure; it's a separate, honestly
distinct kind of number (see `src/tools/quotes.py`).

## Workflow

For any research question, use the **equity-research** skill
(`.claude/skills/equity-research/SKILL.md`). It is the only workflow this
project needs — don't invent an alternative path or spin up subagents for a
single linear research task.

## Output format

Research notes follow this structure: Snapshot → Metrics table → Filing-backed
observations (with citations) → Risks → Open questions → What would change
my mind → View (a stated rating/opinion with its rationale). See the skill
file for the full spec and a worked example.

## Data sources (MVP)

- Portfolio/account: `data/portfolio/mock_account.json` — a mock account,
  not live Robinhood data. Never read or write `data/portfolio/live_*.json`
  (gitignored; reserved for a future real adapter).
- Filings: `data/filings/*.md` — real excerpted 10-K sections with YAML
  front matter (ticker, fiscal year, source URL, fundamentals), chunked and
  searched via deterministic BM25 (`src/tools/filings_search.py`). Covers
  AAPL, MSFT, NKE only.
- Live filings/fundamentals: `src/tools/edgar_client.py`,
  `edgar_fundamentals.py`, `edgar_filings.py` fetch real data from SEC
  EDGAR's free, keyless public APIs (ticker→CIK lookup, XBRL company facts,
  the actual latest 10-K document), disk-cached under `data/edgar_cache/`
  (gitignored). Use for any ticker outside the local corpus.

## State & observability

- Every research run is appended to `data/sessions/runs.jsonl` (never
  edited in place) — tool calls, metrics, citations, note path. Use
  `get_recent_research` before recomputing something already answered this
  session.
- `compute_metrics` is cached to `data/sessions/metrics_cache.json`, keyed by
  ticker + fiscal year + metrics-engine version.
- Every tool call writes a trace line to `logs/traces/<date>.jsonl`
  (latency, cache hit, result size) — useful for debugging, not part of the
  research output itself.

## Evals

`evals/` holds a golden set of research questions and a programmatic rubric
(traceability, citation coverage, banned-language check, required sections,
metric/ticker coverage) plus a retrieval recall@k check. Run `python -m
evals.run` after any change to the metrics engine, retrieval, or the skill
workflow.
