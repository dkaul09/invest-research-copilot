---
name: equity-research
description: Use when the user asks to analyze their portfolio holdings, summarize portfolio risks, compare a holding to peers, explain a company's financial changes using filings, or wants an investment view/rating. Produces a cited research note with a stated, grounded view — never a claim that a trade was actually placed.
---

# Equity Research Workflow

This is the one workflow this project supports. It always follows the same
seven steps, in order, for every research question. Do not skip steps, and
do not state a number or a qualitative claim that didn't come from a tool
call in this workflow.

## Hard rules

- Never place, modify, or cancel a trade, and never claim to have done so.
  There is no tool in this project that can do this — if you ever find
  yourself looking for one, stop, because it means you've misunderstood the
  request. Stating a view (bullish/neutral/bearish, buy/hold/sell) is fine;
  claiming execution ("I've placed this trade," "your order was filled") is
  a fabrication and is always wrong, regardless of what the user asks.
- An investment view is allowed and expected when asked for, but it must be
  traceable to the metrics and citations gathered *this turn* — not a
  generic opinion. State the view, then the specific evidence behind it.
- Never state a number that didn't come out of `compute_metrics`,
  `compare_peers`, `fetch_live_fundamentals`, or `fetch_market_valuation`.
  If you want to say "margins improved," you must have called one of them
  and be quoting its `ratios` output. A multiple from
  `fetch_market_valuation` is market-derived: quote it with its price and
  as-of time, never as a filing fact.
- Never state a qualitative claim about *why* something happened, or the
  basis for a view, without a citation from `search_filings` (ticker +
  section + source_url).
- **A filing outranks a headline.** `fetch_recent_news` is a citation source,
  not a number source. News can raise a risk, add timeliness, or open a
  question — it can never be the sole basis for a View, never contradict a
  filing-derived figure, and never supply a number to the note. If a story
  quotes a figure, either verify it via `fetch_live_fundamentals` /
  `fetch_market_valuation` and cite *that*, or attribute it to the publisher
  as a claim ("Reuters reports…"), not as a fact. There is no sentiment
  score anywhere in this project and you must not invent one: characterize
  tone in prose tied to specific cited articles ("three of five stories this
  week lead on the guidance cut"), never as a number.

## Steps

1. **Restate the question and pick tickers.** Identify which holdings,
   watchlist tickers, or peers the question is actually about. If it's
   ambiguous ("my portfolio"), call `get_portfolio_snapshot` first to see
   what's held before deciding scope.

2. **Gather account context.** Call `get_portfolio_snapshot` (whole
   portfolio questions) or `get_holding_detail` (single-ticker questions) to
   get weights, cost basis, and unrealized P/L. This is read-only context,
   not something to editorialize about — just numbers to carry forward.

2b. **Any figure about the portfolio itself is a computed number too.** A
   weight, a combined weight ("AAPL+MSFT+PLTR is ~72% of the book"), HHI, or
   a top-position share must come from `get_portfolio_snapshot`'s `weights`
   field — add them up from that output, and say whether the weight is of the
   whole account or of invested value only. Approximating from memory is the
   same violation as approximating a margin, and the tilde doesn't excuse it.

3. **Compute metrics.** For each ticker under review, call `compute_metrics`
   if it's in the local corpus (AAPL, MSFT, NKE), or `fetch_live_fundamentals`
   for any other ticker — the latter pulls real numbers from SEC XBRL data.
   If the question turns on valuation — whether something is expensive, how
   much growth is priced in, any request for a rating on a non-corpus
   ticker — also call `fetch_market_valuation`, which is the only tool that
   can produce a P/E or EV/EBITDA. Report what it returns with the price and
   as-of time attached, and never present a multiple as though it came out
   of a filing.
   Together these return quality (margins), leverage (net debt/EBITDA,
   interest coverage, current ratio), valuation (P/E, EV/EBITDA), and growth
   ratios, plus the exact inputs used. `fetch_live_fundamentals` still
   returns `null` for market cap and anything priced off it — that's the
   division of labour, not a failure. Any field that does come back `null`
   carries a reason; state it plainly rather than filling the gap. For
   portfolio concentration, use the `weights`/`hhi`/`top_position_weight` fields
   already present in `get_portfolio_snapshot`.

   **If the account holds any fund, ticker-level concentration understates
   the truth — call `compute_true_exposure`.** A snapshot's HHI treats VOO as
   one position, so an account with two broad funds and a direct mega-cap
   position can look diversified while the same handful of issuers sits
   behind all three. `compute_true_exposure` multiplies each fund's account
   weight through its real N-PORT holdings and reports issuer-level totals.
   Two rules when reporting it: state each fund's holdings as-of date (they
   differ per fund and lag by up to 60 days), and never describe the result
   as a risk measure — it is weight arithmetic and says nothing about how
   those exposures move together.

4. **Retrieve filing evidence.** For each notable metric or risk you plan to
   discuss (e.g. "why did gross margin expand"), call `search_filings`
   (local corpus tickers) or `search_live_filings` (any other ticker) with a
   query aimed at that specific question. Use the returned `section` (local)
   or filing `url` + `filing_date` (live) as the citation. If no relevant
   chunk comes back, say so explicitly — do not fill the gap with your own
   explanation.

   **A live citation has no section heading, so never write one.**
   `search_live_filings` returns only `source_url`, `filing_date`, and the
   passage text — it does not tell you which Item or heading the passage sits
   under. Inventing a plausible-looking one ("Item 1A. Risk Factors —
   Regulatory Matters") fabricates provenance even when the underlying quote
   is accurate. Cite live passages as `(NVDA 10-K filed 2026-02-25, <url>)`
   and, where the wording matters, quote the filing's own phrase. Section
   headings are only for `search_filings` hits, which actually carry a
   `section` field.

4b. **Check recent developments.** Call `fetch_recent_news` for each ticker
   under review. A 10-K can be ten months stale, so this is the only tool that
   can tell you what happened *lately* — it matters most for the Risks, Open
   questions, and What would change my mind sections. Read the headlines and
   summaries; if nothing relevant comes back (or `count` is 0), say so plainly
   rather than reaching for background knowledge about the company. Never pull
   a number out of a headline.

5. **Write the research note**, in this fixed format:
   - **Snapshot** — holdings/weights/cost-basis context relevant to the question
   - **Metrics table** — the `compute_metrics`/`compare_peers` output, one row
     per ticker. Columns are the metric and its value(s) only: no "Source"
     column. Which tool produced a number belongs in the surrounding prose
     (or in the note's own remarks) — as a column it repeats itself on every
     row and squeezes the actual figures into a sliver.
   - **Charts (optional)** — include one only when a shape carries something a
     table row doesn't: ranking several tickers on one measure, or a price
     path over time. Emit it as a fenced ```chart block holding one JSON spec:

     ```chart
     {"type": "bar", "title": "Gross margin, FY2024", "unit": "%",
      "source": "compare_peers(MSFT, [AAPL, NKE])",
      "data": [{"label": "MSFT", "value": 69.8}, {"label": "NKE", "value": 44.6}]}
     ```

     `type` is `bar` (magnitude across tickers) or `line` (a series over
     time, e.g. `get_price_history` output). `unit` is `%`, `$`, `x`, or
     omitted. Percentages go in as 69.8, not 0.698. The rules that are not
     optional: every value must be one a tool returned this turn — a chart
     restates tool output, it never introduces a number, and never smooths or
     interpolates one. One chart carries one measure, because a margin in %
     and leverage in x cannot share an axis — that's two charts. `source`
     names the call the numbers came from and is printed under the chart.
     Charts never replace the metrics table or a citation; they sit
     alongside them.
   - **Filing-backed observations** — each observation ends with a citation like `(NKE 10-K FY2024, "Risk Factors: China Market Exposure")`
   - **Recent developments** — what press coverage from `fetch_recent_news`
     says has happened lately. Each bullet ends with a citation like
     `(Reuters, 2026-08-01, https://…)` — publisher, publish date, URL. Keep
     this separate from Filing-backed observations so a reader can tell at a
     glance which claims rest on a company's own audited disclosure and which
     rest on a journalist's reporting. Characterize tone here in prose tied to
     specific items ("three of five stories lead on the guidance cut"), never
     as a score. If `fetch_recent_news` returned nothing relevant, this section
     says exactly that — "no material coverage in the last N days" is a real
     finding, and better than padding it.
   - **Risks** — bullet list, each grounded in either a metric or a citation
   - **Open questions** — what would need more data or filings to resolve
   - **What would change my mind** — the specific evidence that would shift the assessment
   - **View** — a stated rating (bullish/neutral/bearish, or buy/hold/sell) per ticker discussed, with a one- or two-sentence rationale that points back to specific rows in the metrics table or specific citations above. If the evidence is too thin for a confident view (e.g. `fetch_live_fundamentals` returned mostly `null`), say that plainly instead of forcing a rating.

6. **Self-critique before finishing.** Re-read the note and check: (a) every
   number appears in a `compute_metrics`/`compare_peers` result you actually
   received this turn, (b) every qualitative claim and every stated view has
   a citation or metric it traces back to, (c) nothing claims a trade was
   actually placed, executed, or filled, (d) no number in the note came out of
   a news story rather than a tool, and no stated View rests on press coverage
   alone rather than on metrics and filings. Fix anything that fails before
   presenting the note. This is a check you perform yourself — it is also
   independently enforced by the Stop hook, but don't rely on the hook as
   your only check.

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
| `fetch_market_valuation` | P/E, market cap, EV/EBITDA — the only source of a valuation multiple |
| `search_live_filings` | cited passages from a ticker's actual latest 10-K, any other ticker |
| `fetch_recent_news` | recent press coverage — a citation source for what happened lately, never a number source |

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
