# Investment Research Copilot

I am relatively new to investing, and I wanted something that could give me
objective information about a company and connect to my own portfolio, rather
than digging through filings myself for the same handful of numbers every
time. So I built an agentic RAG copilot that retrieves the financial detail on
demand and writes it up as a cited research note.

It runs on a local MCP server exposing twenty-three tools, nineteen of them
read-only. A metrics engine computes every ratio in pure Python rather than
letting the model guess at one; BM25 retrieval over SEC filing excerpts keeps
every qualitative claim traceable to a cited passage; and a live SEC EDGAR
adapter pulls real XBRL fundamentals and 10-K text for any ticker, not just a
curated corpus. The reasoning is done by Claude, driven through the Anthropic
API with the same system prompt and the same tool contract regardless of which
interface I use.

Account access is read-only by construction. No tool capable of placing,
modifying, or cancelling an instruction exists anywhere in the codebase, so
the copilot can hold an opinion and state a rating, but it can never act on
one. That boundary is enforced in three independent places: the absence of any
such tool, a pre-call hook that denies anything execution-shaped, and a
post-response check that blocks the answer if it ever claims an action was
taken.

I use it through three interfaces — an MCP client, a FastAPI web chat, and a
Telegram bot — all sharing one core, so nothing is reimplemented per surface.

**Recent additions.** Every research note now persists to an append-only
ledger along with the view it stated: the rating, the date, the price it was
quoted at, and the conditions the note said would change its mind. A **track
record** page then lines those past calls up against what prices actually did.
Valuation multiples come from a dedicated tool that combines a quoted price
with filing figures and stamps each result market-derived with its as-of time,
because a multiple goes stale the moment the market moves. Recent press
coverage is available as a citation source, deliberately with no sentiment
score — a polarity number would look computed while tracing back to nothing.
A read-only brokerage connection and price-watch conditions are wired in, with
scheduled delivery of those alerts still to come.

This is a research and learning tool, not a trading system. Every answer is a
research note: metrics, citations, risks, open questions, what would change
the view, and the view itself — never a claim that any instruction was
actually submitted. I started it mainly to get hands-on with agentic AI
patterns: MCP, skills, hooks, and evals.

## What it does

Ask questions like:

- "Analyze my current holdings by quality, leverage, valuation, and concentration."
- "Summarize the main risks across my portfolio."
- "Compare MSFT to peers."
- "Explain why Nike's margins changed using filings."

The assistant:
1. Reads your (mock) portfolio snapshot — read-only.
2. Computes ratios with pure Python — no LLM-guessed numbers.
3. Retrieves cited passages from a local corpus of SEC filing excerpts.
4. Writes a research note with a fixed structure and a self-critique pass.
5. Records the view that note stated — rating, date, and the price it was
   quoted at — into an append-only ledger.

### Track record

Because every note states a dated rating into that ledger, the views can be
lined up afterwards against what prices actually did. The **Track record**
tab in the web UI shows each past call, the price then and now, and whether
the direction held.

Scoring is deliberately crude and says so: direction only, unresolved until
a call is seven days old, and measured against a market price carrying its
own as-of time. It is a record of what was said and what happened next —
not a performance claim, and it says nothing about whether the reasoning was
sound. A general-purpose research tool cannot show you this, because it
never took a position.

### Price-watch conditions

You can also ask any interface to remember a price condition — *"watch NVDA,
tell me if it drops 5% below the previous close"* — and it is saved to
`data/portfolio/alerts.json`. Conditions are **recorded only**: nothing
checks prices yet, so nothing will notify you. The watcher that evaluates
them is future work, and every write says so plainly rather than letting a
saved condition look like an active alarm.

## Setup

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env       # then fill in ANTHROPIC_API_KEY (and TELEGRAM_BOT_TOKEN if using the bot)
pytest -q                 # unit + safety tests
python -m evals.run        # eval scorecard
```

Three ways to use it, all built on the same tools and the same
CLAUDE.md/skill rules — nothing is duplicated per interface:

**1. MCP client (original interface)**
```bash
python -m src.mcp_server   # .mcp.json registers this automatically for any MCP-compatible client
```
`.claude/skills/equity-research/SKILL.md` drives the workflow automatically
when a research question is asked through the MCP client.

**2. Web frontend**
```bash
uvicorn backend.app:app --reload
```
Open `http://localhost:8000`. A FastAPI backend (`backend/app.py`) drives
the same tools and the same system prompt (CLAUDE.md + the skill) directly
against the Anthropic API — no MCP client required. Requires
`ANTHROPIC_API_KEY` in `.env`.

**3. Telegram bot (backup interface)**
```bash
python telegram_bot.py
```
Talks to the exact same `run_research()` function as the web backend — one
core, two interfaces. Create a bot with
[@BotFather](https://t.me/BotFather), put the token in `.env` as
`TELEGRAM_BOT_TOKEN`, and optionally set `TELEGRAM_ALLOWED_CHAT_ID` to your
own chat id (the bot prints it back to you if you message it without that
set) — this bot has no login system, so that's its only access control.

## Trying it out

Everything ships with sample data, so the project is explorable without a
brokerage account and without spending API credits on the first run.

**Sample portfolio.** `data/portfolio/mock_account.json` is a mock account —
holdings, cost basis, cash and a watchlist. It is deliberately unbalanced
(an oversized MSFT position, a losing NKE position, and two overlapping index
funds) so concentration, unrealized-loss and look-through questions have
something to bite on. This is sample data, not a real account.

**Look-through exposure.** `compute_true_exposure` answers the question a
positions list structurally can't: *am I actually diversified?* It multiplies
each held fund's weight in the account by every issuer's weight in that fund's
real N-PORT filing, adds directly held weight, and reports issuer-level
totals. On the sample account — six stocks plus VOO and QQQ — Nvidia,
Alphabet, Amazon, Broadcom, Meta and Tesla all show up as real exposures
despite appearing nowhere in the holdings list, and Apple's true weight is
roughly a fifth higher than its direct position. It's weight arithmetic over
filings, not a risk model, and each fund's holdings carry the quarter-end
they were filed as of.

**Sample track record.** A fresh clone has no research history, so the track
record page starts empty. To populate it:

```bash
python scripts/seed_demo_data.py          # add seven dated sample views
python scripts/seed_demo_data.py --clear  # remove them again
```

Every seeded row is flagged `"sample": true` in the ledger and its note says
so on the first line. The outcomes are mixed on purpose — a scoreboard where
every call was right would be the least believable thing on the page.

**Questions worth asking first:**

- "How much have I invested, and where am I most concentrated?"
- "Give me a research note on NVDA with its current valuation and a view."
- "Compare MSFT to AAPL on margins and leverage."
- "Why did Nike's gross margin move? Cite the filing."
- "What's the recent press coverage on TSLA?"
- "Watch NVDA and tell me if it drops 5% below the previous close."
- "What views have I stated before, and did they hold up?"

The last two are the newer paths: the first records a price condition, the
second reads the ledger.

## Bring your own API key

A deployed instance should not bill the person hosting it. The web UI has an
**API key** field in the sidebar: paste an Anthropic key and it is kept in
that browser's local storage, then sent as an `X-Anthropic-Key` header with
each question. The backend uses it for that one request and never caches it,
logs it, or writes it to the ledger.

If no key is supplied, the backend falls back to `ANTHROPIC_API_KEY` from the
environment, which is what keeps local development and the Telegram bot
working unchanged.

Practical notes:

- Get a key at [console.anthropic.com](https://console.anthropic.com). A
  research note runs several tool iterations, so each question costs a few
  cents on the visitor's own account.
- A rejected key, an account with no credit, and a rate limit each produce a
  plain-language message rather than a raw SDK error.
- Deploy behind HTTPS. The key travels in a request header, so plain HTTP
  would expose it in transit.
- The Telegram bot has no key field and uses the server's environment key, so
  keep `TELEGRAM_ALLOWED_CHAT_ID` set if the host key has credit on it.

## Using it from Telegram

The Telegram bot is the most useful interface in practice — research notes
arrive on a phone, and it is the surface scheduled price alerts will
eventually push to.

1. Message [@BotFather](https://t.me/BotFather) and send `/newbot`. Give it a
   name and a username ending in `bot`. It replies with a token.
2. Put the token in `.env` as `TELEGRAM_BOT_TOKEN`.
3. Start it:
   ```bash
   python telegram_bot.py
   ```
4. Message the bot. If `TELEGRAM_ALLOWED_CHAT_ID` is unset the bot answers
   anyone who finds it; set it to your own chat id to lock it down. The bot
   prints your chat id back to you if you message it with that variable set
   to any other value — that is its only access control, since it has no
   login system of its own.

It calls the same `run_research()` function as the web backend, so the tools,
the system prompt, and the safety checks are identical. Long notes are split
across messages rather than truncated.

## Demo prompts

- "Analyze my current holdings by quality, leverage, valuation, and concentration."
- "Summarize the main risks across my portfolio."
- "Compare MSFT to peers."
- "Explain why Nike's margins changed using its 10-K."
- "What supply chain risks does Apple disclose?"

The local filing corpus (`data/filings/`) covers **AAPL, MSFT, NKE** with
hand-curated fundamentals. Any other ticker (JNJ, XOM, PLTR, or a watchlist
name) is analyzed live instead: `fetch_live_fundamentals` pulls real numbers
from SEC EDGAR's XBRL API, and `search_live_filings` fetches and searches
that company's actual latest 10-K. Some fields (EBITDA, market cap, and
anything derived from them) aren't available this way and come back `null`
rather than estimated.

## Eval baseline

Run `python -m evals.run` to regenerate. As of the initial scaffold, the
reference note builder (a deterministic stand-in for the skill's output,
used to prove the eval mechanism works end-to-end) scores:

| Grader | Mean score | Threshold |
|---|---|---|
| Traceability | 1.000 | 0.95 |
| Citation coverage | 0.900 | 0.80 |
| Safety | 1.000 | 1.00 |
| Structure | 1.000 | 1.00 |
| Coverage | 0.810 | 0.50 |
| Retrieval recall@5 | 0.857 | — |
| Retrieval MRR | 0.779 | — |

All graders pass their threshold; exit code 0. Full detail written to
`evals/results/latest.json` on every run.

## Project structure

```
CLAUDE.md                    project memory: role, hard boundaries, tool contract
.mcp.json                    registers the local MCP server
.claude/settings.json        hook wiring + shell permission deny-list
.claude/hooks/                three guardrail scripts (see below)
.claude/skills/equity-research/SKILL.md   the one research workflow
data/portfolio/mock_account.json          mock holdings, cash, watchlist
data/filings/*.md             SEC filing excerpts (front matter + fundamentals)
src/adapters/                 PortfolioAdapter contract + future Robinhood stub
src/tools/                    metrics engine, filings search, peer compare, mock portfolio
src/tools/edgar_*.py          live SEC EDGAR adapter: CIK lookup, XBRL fundamentals, live filing search
src/state/                    session ledger + metrics cache
src/state/track_record.py     scores recorded views against realized price moves
src/tools/alerts.py           price-watch condition store
backend/view_extract.py       pulls the structured view out of a finished note
src/obs/trace.py              per-tool-call JSONL tracing
src/safety.py                 shared banned-language check (hook, evals, and backend all use this one copy)
src/tool_router.py            the eighteen tool implementations, shared by mcp_server.py and backend/app.py
src/mcp_server.py             MCP surface for MCP clients (wraps tool_router)
backend/app.py                FastAPI backend: Anthropic agent loop for the web + Telegram frontends
web/                          plain HTML/CSS/JS chat frontend, served by backend/app.py
telegram_bot.py               Telegram bot, backup interface to the same backend
evals/                        golden set, rubric graders, retrieval eval, runner
tests/                        safety, workflow, and grader tests
```

## Why this is agentic

It's easy to build something that looks agentic but is really just a chatbot
wrapped around static data, or conversely something so deterministic it
never needs a model at all. This project draws the line deliberately:

- **Deterministic** — all arithmetic. `metrics_engine.py` computes every
  ratio in pure Python and returns `None` rather than a guess when an input
  is missing. `filings_search.py`'s ranking is a fixed algorithm, not a
  model call: the same query against the same corpus and backend always
  ranks the same way. The eval
  graders (`evals/graders.py`) are also deterministic — no LLM-as-judge in
  the MVP.
- **Agentic** — planning and judgment. Deciding which tickers a vague
  question ("my portfolio") actually concerns, which metrics matter for a
  given question, which filing sections to search for, how to synthesize a
  metrics table and citations into a coherent note, and the self-critique
  pass that checks the note before it's shown — all of this is genuine
  agent behavior encoded in the `equity-research` skill, not scripted.
- **Retrieval** — `data/filings/*.md` is chunked by section and ranked by
  **BM25 and dense embeddings fused with Reciprocal Rank Fusion**; every
  result carries `(ticker, section, source_url)` so a claim in a note can
  always be traced to a specific filing passage. Lexical matching alone
  missed passages that describe a risk without naming it — a section about
  "suppliers" and "contract manufacturers" scored 0.0 for "supply chain
  concentration" — so both rankers run and their results are unioned.
  Embeddings are optional: with no backend the system degrades to pure
  BM25 and says so on every hit.
- **Guardrail logic** — safety is structural, not just prompted, and it's
  scoped to what actually needs enforcing: this tool may state an opinion
  (bullish/neutral/bearish, buy/hold/sell), but it can never *act* on one.
  Tools are read-only by construction (no write method exists to misuse) —
  true for every interface, since the MCP server, the web backend, and the
  Telegram bot all call the same eighteen functions in `src/tool_router.py`.
  In the MCP client, a `PreToolUse` hook hard-denies any tool call shaped
  like order execution, a `Stop` hook blocks the turn if the final response
  claims a trade was actually placed/executed/filled (a fabrication, since
  no tool can do that), and a `UserPromptSubmit` hook warns (never blocks)
  so "should I buy X" gets an actual view, not a canned refusal. Outside
  that client (web/Telegram), `backend/app.py` runs the same check
  (`src/safety.py` — one shared module, not a re-implementation) against
  every final response before it reaches the user, giving the model one
  chance to rewrite before the response is withheld entirely.

## Live SEC EDGAR adapter

`fetch_live_fundamentals` and `search_live_filings` reach SEC EDGAR's free,
keyless public APIs — no API key or auth, just a descriptive `User-Agent`
header per SEC's usage policy. For any ticker:

1. **Ticker → CIK** via `https://www.sec.gov/files/company_tickers.json`.
2. **Fundamentals** via the XBRL company-facts API
   (`data.sec.gov/api/xbrl/companyfacts/CIK##########.json`) — every number
   is a real value SEC's own XBRL data reports for a specific US-GAAP tag
   on the latest annual filing. Missing tags come back `null`, never
   estimated. EBITDA is derived from the operating-income and D&A lines the
   filer actually tagged, so it resolves for most companies and stays `null`
   for the rest rather than being estimated. Market cap, P/E and EV/EBITDA
   stay `null` here by design — a multiple cannot come from a filing alone.
   `fetch_market_valuation` computes those from a quoted price plus filing
   figures, and stamps every one of them market-derived with its as-of time.
3. **Filing text** via the company's actual latest 10-K document
   (fetched from `sec.gov/Archives/edgar/...`), stripped of HTML and
   chunked into overlapping ~200-word windows, then ranked with the same
   hybrid BM25 + embedding retrieval as the local corpus. This path has no
   section headings to lean on, so the dense half carries more weight here
   than it does over the curated corpus.

Everything is disk-cached to `data/edgar_cache/` (gitignored) so repeat
questions about the same ticker don't re-hit the network.

## Future work (explicitly out of scope for the MVP)

- **Live Robinhood adapter** — `src/adapters/robinhood_readonly.py` documents
  the constraints (read-only scope, no execution-capable methods) a real
  adapter must satisfy. Not implemented; raises `NotImplementedError`. This
  is unrelated to the EDGAR adapter above — brokerage/account access is a
  separate, still-future integration.
- **The alert watcher** — price-watch conditions are recorded today but
  nothing evaluates them. The watcher, sustain windows, cooldowns, quiet
  hours, notification tiers and Telegram push are specified in
  `docs/superpowers/specs/2026-08-04-price-alerts-design.md`. It needs a
  narrow amendment to CLAUDE.md first: the project currently promises it
  "does not monitor the market", which a scheduled poller would break.
- **Calibration scoring** — the ledger now holds dated ratings and the
  conditions each note said would change it, which is the substrate for
  scoring reasoning quality rather than just direction.
- **LLM-judge eval stage** — the current eval is entirely programmatic. A
  richer eval could add an LLM grader for note *quality* (not just
  structure/traceability), verified against the programmatic checks rather
  than replacing them.

---

## Status and feedback

This project is actively in progress, so expect bugs. Some parts are
deliberately incomplete. The portfolio is a mock account rather than live
brokerage data. Price-watch conditions are recorded but nothing delivers them
yet. The track record scores direction only, over a seven day window, and
anything labelled sample data is exactly that.

Nothing here is financial advice. It is a research and learning tool that
states an objective, sourced view, and it cannot act on one.

If you find a bug, want something changed, or have a suggestion, I would
genuinely like to hear it. Email me at dhruv.kau@usc.edu.
