---
name: equity-research
description: Use when the user asks to analyze their portfolio holdings, summarize portfolio risks, compare a holding to peers, or explain a company's financial changes using filings. Produces a cited research note — never a buy/sell recommendation.
---

# Equity Research Workflow

This is the one workflow this project supports. It always follows the same
six steps, in order, for every research question. Do not skip steps, and do
not state a number or a qualitative claim that didn't come from a tool call
in this workflow.

## Hard rules

- Never place, modify, or cancel a trade. There is no tool in this project
  that can do this — if you ever find yourself looking for one, stop, because
  it means you've misunderstood the request.
- Never use recommendation language: no "you should buy/sell", "place this
  trade", "strong buy", "sell immediately". Use: *research note*, *risks*,
  *open questions*, *watchlist candidate*, *needs more evidence*.
- Never state a number that didn't come out of `compute_metrics` or
  `compare_peers`. If you want to say "margins improved," you must have
  called `compute_metrics` and be quoting its `ratios` output.
- Never state a qualitative claim about *why* something happened without a
  citation from `search_filings` (ticker + section + source_url).

## Steps

1. **Restate the question and pick tickers.** Identify which holdings,
   watchlist tickers, or peers the question is actually about. If it's
   ambiguous ("my portfolio"), call `get_portfolio_snapshot` first to see
   what's held before deciding scope.

2. **Gather account context.** Call `get_portfolio_snapshot` (whole
   portfolio questions) or `get_holding_detail` (single-ticker questions) to
   get weights, cost basis, and unrealized P/L. This is read-only context,
   not something to editorialize about — just numbers to carry forward.

3. **Compute metrics.** For each ticker under review, call `compute_metrics`
   if it's in the local corpus (AAPL, MSFT, NKE), or `fetch_live_fundamentals`
   for any other ticker — the latter pulls real numbers from SEC XBRL data.
   This returns quality (margins), leverage (net debt/EBITDA, interest
   coverage, current ratio), valuation (P/E, EV/EBITDA), and growth ratios,
   plus the exact inputs used. Some fields from `fetch_live_fundamentals`
   (EBITDA, market cap, and anything derived from them) will be `null` —
   state that plainly rather than filling the gap. For portfolio
   concentration, use the `weights`/`hhi`/`top_position_weight` fields
   already present in `get_portfolio_snapshot`.

4. **Retrieve filing evidence.** For each notable metric or risk you plan to
   discuss (e.g. "why did gross margin expand"), call `search_filings`
   (local corpus tickers) or `search_live_filings` (any other ticker) with a
   query aimed at that specific question. Use the returned `section` (local)
   or filing `url` + `filing_date` (live) as the citation. If no relevant
   chunk comes back, say so explicitly — do not fill the gap with your own
   explanation.

5. **Write the research note**, in this fixed format:
   - **Snapshot** — holdings/weights/cost-basis context relevant to the question
   - **Metrics table** — the `compute_metrics`/`compare_peers` output, one row per ticker
   - **Filing-backed observations** — each observation ends with a citation like `(NKE 10-K FY2024, "Risk Factors: China Market Exposure")`
   - **Risks** — bullet list, each grounded in either a metric or a citation
   - **Open questions** — what would need more data or filings to resolve
   - **What would change my mind** — the specific evidence that would shift the assessment

6. **Self-critique before finishing.** Re-read the note and check: (a) every
   number appears in a `compute_metrics`/`compare_peers` result you actually
   received this turn, (b) every qualitative claim has a citation, (c) no
   banned recommendation language appears anywhere. Fix anything that fails
   before presenting the note. This is a check you perform yourself — it is
   also independently enforced by the Stop hook, but don't rely on the hook
   as your only check.

## Tool reference

| Tool | Use for |
|---|---|
| `get_portfolio_snapshot` | whole-account view, concentration, weights |
| `get_holding_detail` | one held ticker's position detail |
| `compute_metrics` | deterministic ratios, local-corpus ticker (AAPL/MSFT/NKE) |
| `search_filings` | cited passages, local corpus ticker |
| `compare_peers` | side-by-side metric table vs named peers (local corpus) |
| `get_recent_research` | prior runs, for follow-up questions |
| `fetch_live_fundamentals` | deterministic ratios from real SEC XBRL data, any other ticker |
| `search_live_filings` | cited passages from a ticker's actual latest 10-K, any other ticker |

## Example

**Q:** "Analyze my current holdings by quality, leverage, valuation, and concentration."

1. `get_portfolio_snapshot` → six holdings, MSFT is ~35% of invested value.
2. `compute_metrics` for each ticker with fundamentals available locally
   (AAPL, MSFT, NKE — others are noted as outside the local filing corpus).
3. `search_filings("margin", ticker="NKE")` → risk-factor and MD&A passages
   explaining NKE's margin dynamics.
4. Write the note: snapshot notes MSFT concentration and the HHI value;
   metrics table shows margins/leverage/valuation per ticker; observations
   cite the NKE wholesale-transition and MSFT AI-capex risk sections;
   risks section flags concentration and margin-pressure risk; open
   questions note that AMD/COST/DIS/JNJ/XOM/PLTR fundamentals aren't in the
   local corpus yet.
