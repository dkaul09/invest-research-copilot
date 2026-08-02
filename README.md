# Investment Research Copilot (MVP)

A personal, **read-only** portfolio research assistant built as a Claude Code
project. It analyzes your holdings and watchlist using deterministic
financial metrics and filing-backed evidence — it does not place trades, and
it cannot be made to, by construction.

This is a learning tool, not a trading system. Every answer is a research
note: metrics, citations, risks, and open questions — never a "buy this" /
"sell this" recommendation.

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

## Setup

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
pytest -q                 # unit + safety tests
python -m evals.run        # eval scorecard
python -m src.mcp_server   # start the MCP server standalone (Ctrl+C to stop)
```

Then open this folder in Claude Code — `.mcp.json` registers the tool
server and `.claude/skills/equity-research/SKILL.md` drives the workflow
automatically when you ask a research question.

## Demo prompts

- "Analyze my current holdings by quality, leverage, valuation, and concentration."
- "Summarize the main risks across my portfolio."
- "Compare MSFT to peers."
- "Explain why Nike's margins changed using its 10-K."
- "What supply chain risks does Apple disclose?"

The local filing corpus (`data/filings/`) currently covers **AAPL, MSFT,
NKE**. Other holdings (JNJ, XOM, PLTR) and watchlist tickers will be
reported as outside the corpus rather than analyzed with fabricated
numbers.

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
src/state/                    session ledger + metrics cache
src/obs/trace.py              per-tool-call JSONL tracing
src/mcp_server.py             the six read-only MCP tools
evals/                        golden set, rubric graders, retrieval eval, runner
tests/                        safety, workflow, and grader tests
```

## Why this is agentic

It's easy to build something that looks agentic but is really just a chatbot
wrapped around static data, or conversely something so deterministic it
never needs a model at all. This project draws the line deliberately:

- **Deterministic** — all arithmetic. `metrics_engine.py` computes every
  ratio in pure Python and returns `None` rather than a guess when an input
  is missing. `filings_search.py`'s BM25 ranking is a fixed algorithm, not a
  model call: the same query always returns the same ordering. The eval
  graders (`evals/graders.py`) are also deterministic — no LLM-as-judge in
  the MVP.
- **Agentic** — planning and judgment. Deciding which tickers a vague
  question ("my portfolio") actually concerns, which metrics matter for a
  given question, which filing sections to search for, how to synthesize a
  metrics table and citations into a coherent note, and the self-critique
  pass that checks the note before it's shown — all of this is genuine
  agent behavior encoded in the `equity-research` skill, not scripted.
- **Retrieval** — `data/filings/*.md` is chunked by section and ranked with
  BM25; every result carries `(ticker, section, source_url)` so a claim in a
  note can always be traced to a specific filing passage.
- **Guardrail logic** — safety is structural, not just prompted. Tools are
  read-only by construction (no write method exists to misuse). A
  `PreToolUse` hook hard-denies any tool call shaped like order execution. A
  `Stop` hook scans the final response for banned recommendation language
  and blocks the turn until it's rewritten. A `UserPromptSubmit` hook warns
  (never blocks) so legitimate research questions about "selling" a
  division still work.

## Future work (explicitly out of scope for the MVP)

- **Live Robinhood adapter** — `src/adapters/robinhood_readonly.py` documents
  the constraints (read-only scope, no execution-capable methods) a real
  adapter must satisfy. Not implemented; raises `NotImplementedError`.
- **Live EDGAR fetch** — the retrieval layer works against a small local
  corpus. A future adapter could fetch and cache real filings from SEC
  EDGAR's full-text search API, but that adds network dependency and test
  complexity this MVP intentionally avoids.
- **LLM-judge eval stage** — the current eval is entirely programmatic. A
  richer eval could add an LLM grader for note *quality* (not just
  structure/traceability), verified against the programmatic checks rather
  than replacing them.
