# Fund research (index funds / ETFs) — design

**Date:** 2026-08-09
**Status:** approved, implementing

## Problem

The project can research operating companies and nothing else. Asked about
VOO, VXUS, or QQQ, every grounding tool it has returns nothing: an ETF files
no 10-K and has no XBRL company facts, so `compute_metrics`,
`fetch_live_fundamentals`, and `search_live_filings` are all dead ends. The
project's central rule — every number from a tool, every qualitative claim
from a filing citation — has no data source to stand on for funds.

`edgar_client.py` already anticipates this: its error messages say "this is
often an ETF, index, or fund rather than an operating company." That error
is the feature request.

## Scope

**US-listed, US-domiciled funds only.** VOO, VXUS, QQQ, IVV and the like.
Non-US and UCITS funds (CSPX) are refused explicitly, never guessed at —
there is no EDGAR equivalent for Irish-domiciled funds, and fabricating
around that would break the project's core promise.

Implementation note: ticker collisions across markets are a real hazard
here, and worse than a plain miss. VUSA resolves *successfully* — to a US
fund in Tidal Trust III — and is not Vanguard's LSE-listed S&P 500 UCITS
that a user typing "VUSA" probably means. The registry can't detect this,
so every fund answer reads back the registrant name for the user to catch.

Explicitly out of scope: performance prediction, tax advice, and any
directional recommendation (see Output contract).

## Data sources

Two layers, kept separate and labelled, mirroring how
`market_valuation.py` already separates filing figures from market prices.

**Primary — SEC EDGAR.** Funds do file, just not 10-Ks:

| Form | Supplies |
|---|---|
| 485BPOS | Prospectus: objective, benchmark, stated expense ratio, replication method, distribution policy |
| N-CEN | Annual report: securities lending activity |
| N-PORT | Quarterly full portfolio holdings |

Ticker → filer is resolved through SEC's `company_tickers_mf.json`, which
maps a fund ticker to `(cik, seriesId, classId)`. Verified working:
VOO → 36405/S000002839/C000092055, VXUS → 736054/S000002932/C000094038,
QQQ → 1067839/S000101292/C000271435.

**Vendor — yfinance.** The live layer: current expense ratio, AUM,
turnover, top-10 holdings, sector weights, category, index description.
Verified working for VXUS (0.05% expense ratio, $54.97B net assets).

## Data contract

Every field a fund tool returns carries `{value, source, as_of}`, where
`source` is one of:

- `filing` — an EDGAR document, with its URL
- `vendor` — yfinance/Yahoo, stamped with fetch time
- `computed` — derived in-process, with its inputs named

This makes "separate reported facts, calculated results, and
interpretation" a property of the data rather than something the model has
to remember. Unavailable fields return `null` with a reason string. Nothing
is ever estimated.

## Modules

- `src/tools/fund_registry.py` — ticker → `(cik, series_id, class_id)` from
  `company_tickers_mf.json`, disk-cached via `edgar_client`. Returns
  explicit `not_a_fund` (equities), `not_covered` (non-US, and UITs like
  SPY that are absent from the mapping). This is the clarification gate:
  ambiguity stops here and asks rather than guessing.
- `src/tools/fund_filings.py` — fetches 485BPOS / N-CEN / N-PORT for a
  fund's CIK and BM25-searches their text. Reuses `_html_to_text`,
  `_windowed_chunks`, and `_BM25` from `edgar_filings.py` rather than
  duplicating them.
- `src/tools/fund_holdings.py` — parses the fund's full portfolio out of
  its N-PORT XML: holdings, weights, ISIN/CUSIP, and issuer country. One
  N-PORT is filed per series and EDGAR's index doesn't say which is which,
  so this walks recent filings until the `seriesId` matches, bounded and
  disk-cached.
- `src/tools/fund_profile.py` — the vendor layer, every field stamped.
- `src/tools/fund_overlap.py` — pure computation over the other modules'
  output: intersects fund holdings with account holdings, returns overlap
  weight and post-add look-through exposure.
- `src/tools/fund_compare.py` — side-by-side across funds on one mandate.

## Tools

Four new MCP tools (18 → 22), all `readOnlyHint`; three `openWorldHint`.

| Tool | Purpose |
|---|---|
| `get_fund_profile` | expense ratio, AUM, index, holdings count, top-10, sector mix, asset classes |
| `search_fund_filings` | cited passages from a fund's prospectus / N-CEN / N-PORT |
| `compare_funds` | side-by-side across funds with the same mandate |
| `compute_fund_overlap` | look-through overlap with current account holdings |

## Output contract — deliberately different from equities

Funds get a **due-diligence memo, not a rating.** Where the equity note
ends in a View section with a bullish/neutral/bearish call, the fund memo
ends in "what would make me avoid this fund?" and "what exposure this does
NOT provide." No directional recommendation, no predicted return.

This is a narrowing of the project default (CLAUDE.md encourages a stated
view) and applies to funds only. Two skills, two contracts, no blurring.

Memo sections:

1. Objective, benchmark, domicile, currency, exchange, distribution policy
2. Expense ratio, AUM, replication method, securities lending, tracking difference
3. Geographic, sector, market-cap, and top-10 exposure
4. Main risks and scenarios where the fund underperforms
5. Suitable long-term use, and what exposure it does *not* provide
6. Comparable alternatives with the same mandate
7. What would make me avoid this fund

Implemented as a separate skill, `.claude/skills/fund-research/SKILL.md`.

## Honest gaps — null with a reason, not a guess

- **Tracking difference** requires index total returns, which no free
  source provides. Always `null` with that reason attached. Conspicuously
  absent beats silently wrong.
- **Geographic exposure** — *resolved during implementation, better than
  planned.* The vendor feed has no country breakdown, but N-PORT tags every
  position with `invCountry`, so country weights are computed by
  aggregation and are **filing-sourced**, not a vendor summary and not a
  qualitative gesture at the prospectus. This also made full holdings and a
  real (not top-10-floor) overlap calculation possible, so
  `fund_holdings.py` was added to the module list.
- **N-PORT lags a quarter.** Overlap math is stamped as-of the N-PORT date,
  never described as current exposure.
- **Yahoo's `equity_holdings` "Price/Earnings"** is an earnings yield
  (VXUS: 0.055), not a P/E. The field is excluded entirely rather than
  surfaced mislabeled.

## Safety

The Stop hook cannot blanket-ban directional language, because equities
legitimately use it. It gains one addition banned on *both* paths:
return-promising ("will return", "expect X% annually", "should
outperform"). The fund no-rating rule is enforced by the skill and by
evals, not by the hook.

## Testing

- Unit tests for `fund_registry` resolution and its three refusal cases,
  for the source-stamping contract, and for overlap arithmetic.
- Eval additions: golden fund questions, plus rubric checks for
  no-rating-in-fund-memos, source-tag coverage, and as-of presence.
