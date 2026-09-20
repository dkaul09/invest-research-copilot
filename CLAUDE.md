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
- **Never state a number that wasn't produced by `compute_metrics`,
  `compare_peers`, `fetch_live_fundamentals`, or `fetch_market_valuation`.**
  Every ratio, margin, weight, or growth figure in a response must trace
  back to one of those tool calls. Do not estimate, round mentally, or
  recall a figure "from memory."
- **A valuation multiple is a market-derived number and must be reported as
  one.** `fetch_market_valuation` mixes a quoted price with filing figures,
  so P/E, market cap, and EV/EBITDA always carry the price and as-of time
  they were computed at ("P/E 42.4x at $207.96, as of 2026-08-03"), never a
  bare figure presented like a filing fact. A margin from a 10-K stays true
  until the next 10-K; a multiple is stale as soon as the market moves.
- **Never state a qualitative claim (why something happened, a risk, a
  trend, or the basis for a view) without a citation from `search_filings`**
  — ticker, section heading, and source URL. No citation, no claim. A view
  or rating must be traceable to the metrics/citations gathered this turn,
  not asserted from nowhere.
- **A headline is press coverage, and must be reported as one — a filing
  outranks it.** `fetch_recent_news` is a citation source, not a number
  source: cite an article by publisher, date, and URL, and never state a
  figure that appeared only in a news story as though a tool produced it.
  News can raise a risk, add timeliness, or open a question; it can never be
  the sole basis for a view or contradict a filing-derived figure. There is
  deliberately **no sentiment score** anywhere in this project and none may
  be invented — a polarity number traces back to nothing but a model's
  judgment while looking computed. Characterize tone in prose tied to
  specific cited articles instead.
- Robinhood (or any brokerage) integration, if added later, is **read-only
  by construction**: holdings, cost basis, watchlist, and cash only. See
  `src/adapters/robinhood_readonly.py` for the documented constraints any
  future adapter must satisfy. This is unrelated to and separate from the
  live EDGAR adapter below — EDGAR is public filing data, never account or
  brokerage data.
- The **price-watch store** (`src/tools/alerts.py`,
  `data/portfolio/alerts.json`) is writable for the same reason the
  watchlist is: a condition you want to be told about is a personal to-do.
  It records conditions only — nothing evaluates or delivers them yet, and
  a saved condition must never be described as an active alarm. Nothing in
  it can act.
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
evidence, recent developments, press coverage, news-backed observation,
reported, according to <publisher>.*

Never claim an action was actually taken: *I've placed/executed/submitted
this trade, your order was filled, order confirmed, I bought/sold X.* These
are fabrications, not opinions — no tool exists to make them true.

A Stop hook (`.claude/hooks/check_output_language.py`) scans every final
response for this specific fabrication pattern and blocks the turn until
it's rewritten — but that hook is a backstop, not a substitute for writing
correctly the first time.

## Tool contract

Twenty-three MCP tools, served by `src/mcp_server.py` (see `.mcp.json`).
Nineteen are read-only (`readOnlyHint: true`); `add_to_watchlist`,
`remove_from_watchlist`, `add_price_alert` and `remove_price_alert` are the
deliberate exceptions — a personal
watchlist is a tracking list, not account or trade data, so it's fine for
it to be genuinely writable. Eleven tools reach public network APIs (SEC
EDGAR, live quote data, or the news feed) and are annotated
`openWorldHint: true`:

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
| `fetch_market_valuation` | P/E, market cap, EV/EBITDA from a live price + filing figures |
| `fetch_recent_news` | recent press coverage — headline, publisher, URL, date; a citation source, never a number source |
| `add_price_alert` / `list_price_alerts` / `remove_price_alert` | record price conditions to be notified about later — saved only, nothing checks prices yet |
| `get_fund_profile` | an index fund/ETF's expense ratio, net assets, turnover, top holdings, sector mix — every field stamped with its source |
| `search_fund_filings` | cited passages from a fund's real prospectus (497K, 485BPOS) and annual report (N-CSR) |
| `compare_funds` | side-by-side cost/scale/concentration across funds with the same mandate |
| `compute_fund_overlap` | how much of a fund the account already holds, from the fund's actual N-PORT holdings |
| `compute_true_exposure` | issuer-level exposure across the whole account, looking through every fund held to its N-PORT holdings — answers "am I actually diversified?" |

The local filing corpus (`data/filings/`) covers **AAPL, MSFT, NKE** with
hand-curated fundamentals. For any other ticker, use `fetch_live_fundamentals`
and `search_live_filings` instead of fabricating numbers or evidence —
they pull real data from SEC EDGAR. EBITDA is derived from the operating
income and D&A lines the filer actually tagged, so it resolves for most
companies and stays `null` for the rest rather than being estimated.
Market cap, P/E, and EV/EBITDA are still `null` from
`fetch_live_fundamentals` by design — a multiple can't come from a filing
alone. Call `fetch_market_valuation` when a question turns on valuation,
and say plainly when a figure comes back `null` with a reason attached.

`get_quote`/`get_price_history` return **market price data, not a
financial ratio** — never pass a live price into `compute_metrics` or
state it as though it were a computed figure; it's a separate, honestly
distinct kind of number (see `src/tools/quotes.py`). The one sanctioned
path from a price to a ratio is `fetch_market_valuation`
(`src/tools/market_valuation.py`), which keeps the two halves labelled:
`metrics_engine.compute_ratios` remains filing-only and never sees a
price, while every multiple that tool returns is stamped market-derived
with its as-of time.

## Workflow

Two workflows, picked by what's being researched:

- A **company** — use the **equity-research** skill
  (`.claude/skills/equity-research/SKILL.md`).
- An **index fund or ETF** (VOO, VXUS, QQQ) — use the **fund-research**
  skill (`.claude/skills/fund-research/SKILL.md`).

These are the only two workflows this project needs — don't invent an
alternative path or spin up subagents for a single linear research task.

The split isn't stylistic. An ETF files no 10-K and has no XBRL company
facts, so `compute_metrics`, `fetch_live_fundamentals`, and
`search_live_filings` structurally cannot answer a question about a fund;
reaching for them on VOO means you're on the wrong path.

## Output format

Research notes follow this structure: Snapshot → Metrics table → Filing-backed
observations (with citations) → Risks → Open questions → What would change
my mind → View (a stated rating/opinion with its rationale). See the skill
file for the full spec and a worked example.

**Fund memos are the one deliberate exception to the "state a view" rule.**
A fund memo runs Mandate → Cost and structure → Exposure → Risks →
Portfolio fit and what it does *not* give you → Comparable alternatives →
What would make me avoid this fund. It states **no rating and no
directional call**: what makes an index fund right for someone depends on a
whole portfolio and a set of goals this project can't see, whereas the
facts about the fund — cost, exposure, concentration, overlap — are exactly
what it can establish. Saying what would make the fund unsuitable is
in scope; saying whether to own it is not.

Promising a return or predicting performance is banned on **both** paths
and is blocked by the Stop hook. A view is groundable in evidence; a
forecast is not.

## Data sources (MVP)

- Portfolio/account: `data/portfolio/mock_account.json` — a mock account,
  used by every research tool. Never read or write
  `data/portfolio/live_*.json` (gitignored).
- Live brokerage account: **read-only, and opt-in.** `src/adapters/`
  `rh_oauth.py` + `rh_mcp_client.py` + `robinhood_live.py` connect the
  dashboard to Robinhood's agent MCP endpoint over OAuth 2.1 (dynamic
  registration, PKCE, refresh tokens; no password reaches this backend).
  Tokens live in `data/portfolio/.rh_token.json`, gitignored and written
  `0600`. This powers the dashboard's Live account panel only — the
  research tools still read the mock fixture.

  **Read the deviation before touching this.** `adapters/base.py` requires
  brokerage credentials be scoped read-only *at the provider*. Robinhood
  publishes exactly one scope, `internal`, so that is not achievable: the
  token is full-power. The guarantee is reconstructed in
  `rh_mcp_client.py` by an **allowlist** of four read tools
  (`get_accounts`, `get_portfolio`, `get_equity_positions`,
  `get_equity_quotes`), with no caller-supplied tool name reachable from
  any HTTP route. It is an allowlist, not a denylist, because a denylist
  fails open the moment the remote server adds a tool. Adding a fifth tool
  is a security decision. The one provider-side guarantee is that the
  default account reports `agentic_allowed: false`.
- Filings: `data/filings/*.md` — real excerpted 10-K sections with YAML
  front matter (ticker, fiscal year, source URL, fundamentals), chunked by
  section and searched via **hybrid retrieval** (`src/tools/filings_search.py`).
  Covers AAPL, MSFT, NKE only.
- Retrieval is **BM25 + dense embeddings fused with Reciprocal Rank
  Fusion** (`src/tools/embeddings.py`, `src/tools/hybrid_search.py`), on
  all three corpora — local filings, live 10-Ks, fund prospectuses. BM25
  alone had a real failure mode: AAPL's "Risk Factors: Supply Chain
  Concentration" section never writes *supply*, *chain*, or *concentration*
  in its body (it says "suppliers", "contract manufacturers"), so a lexical
  query for it scored that chunk 0.0 and ranked a margin discussion first.
  Three things to know before touching this:
  - **Embeddings are optional and degrade honestly.** With no backend
    installed, or `IRC_EMBEDDINGS=off`, search falls back to pure BM25 and
    every hit reports `retrieval.backend: "none"`. It never fakes a vector.
  - **The default backend is local** (`model2vec`, static embeddings on
    numpy — no torch, no API key, no network at query time). If
    `VOYAGE_API_KEY` is set, the finance-tuned `voyage-finance-2` is used
    instead. Vectors are cached to `data/embedding_cache/` keyed by content
    hash *plus backend id*, so switching models can't read stale vectors.
  - **Fusion is rank-based, not score-based**, so there is no weight to
    retune per corpus, and retrieval stays deterministic — which is what
    keeps `evals/retrieval_eval.py` meaningful. Every hit carries
    `retrieval.bm25_rank` / `retrieval.dense_rank` so you can see which
    ranker found it.
- Live filings/fundamentals: `src/tools/edgar_client.py`,
  `edgar_fundamentals.py`, `edgar_filings.py` fetch real data from SEC
  EDGAR's free, keyless public APIs (ticker→CIK lookup, XBRL company facts,
  the actual latest 10-K document), disk-cached under `data/edgar_cache/`
  (gitignored). Use for any ticker outside the local corpus.
- Funds: **US-domiciled funds only.** `src/tools/fund_registry.py` resolves
  a fund ticker through SEC's `company_tickers_mf.json` to the trust that
  files for it, plus its series and class IDs. `fund_filings.py` searches
  the trust's real prospectus and annual report; `fund_holdings.py` parses
  the fund's full portfolio out of its N-PORT XML (holdings, weights, and
  issuer country, all filing-sourced); `fund_profile.py` supplies the live
  vendor layer; `fund_overlap.py`, `fund_compare.py` and
  `true_exposure.py` compute on top of those. `true_exposure.py` is the
  whole-account counterpart to `fund_overlap.py`: overlap asks what a
  *candidate* fund duplicates, true exposure asks what the account already
  owns once every held fund is unpacked to issuers. It is weight arithmetic
  and must never be described as a risk or correlation model. Three constraints worth knowing before writing a memo:
  - **Every fund field carries `{value, source, as_of}`**, where `source`
    is `filing`, `vendor` (a Yahoo summary, not a primary source), or
    `computed`. Report the label, don't launder a vendor figure into a
    fact. A prospectus outranks a vendor summary.
  - **N-PORT lags.** Holdings are as of a quarter-end filed up to 60 days
    later. State that date; never call them current holdings.
  - **Prospectuses are trust-level**, covering many sibling funds. Confirm
    a retrieved passage names the specific fund before citing it.
  Non-US and UCITS funds have no EDGAR presence and are refused explicitly,
  as are unit investment trusts like SPY. Watch for ticker collisions
  across markets — VUSA resolves to a US fund in Tidal Trust III, not
  Vanguard's LSE-listed UCITS. Tracking difference is permanently
  unavailable: it needs index total returns that no free source provides.
- News: `src/tools/news.py` reads Yahoo Finance's per-ticker news feed via
  `yfinance` (keyless, already a dependency). The feed mixes wire services
  with low-quality aggregators, which is exactly why every article carries
  its publisher — a reader discounts the source themselves, which a
  sentiment score would have silently averaged away.

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
