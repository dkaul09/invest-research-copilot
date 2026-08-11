---
name: fund-research
description: Use when the user asks about an index fund or ETF — S&P 500 funds, VOO, VXUS, QQQ, total-market or international funds, expense ratios, fund holdings, fund overlap with the portfolio, or comparing two funds tracking the same index. Produces a cited due-diligence memo with no rating and no directional call.
---

# Fund Research Workflow

This is the workflow for index funds and ETFs. It is **not** the
equity-research workflow with different tools — the output contract is
deliberately different, and mixing them is the main way to get this wrong.

**An ETF is not a company.** It files no 10-K and has no XBRL company
facts. `compute_metrics`, `fetch_live_fundamentals`, and
`search_live_filings` cannot answer anything about VOO or VXUS, and calling
them is a signal you've taken the wrong path. Use the four fund tools.

## The one difference from equity research

Equity research ends in a **View** — a rating, grounded in the evidence.
Fund research does not. A fund memo ends in **"What would make me avoid
this fund"**, and states no rating, no directional call, and no predicted
return. This is deliberate: the interesting question about an index fund is
what exposure it gives you and at what cost, not whether someone should own
it — that depends on a whole portfolio and a set of goals this project
cannot see.

If the user explicitly asks whether they should own VOO, answer with the
memo, say plainly that this workflow states fund characteristics and
trade-offs rather than a directional call, and name the specific facts that
would matter most to that decision.

## Hard rules

- **Never state a fund fact you didn't retrieve this turn.** Expense
  ratios, holdings, benchmarks, and net assets all come from
  `get_fund_profile`, `search_fund_filings`, `compare_funds`, or
  `compute_fund_overlap`. You know a lot of plausible fund facts from
  training; every one of them is a fabrication in this context.
- **Label every number with its source and date.** The tools return
  `{value, source, as_of}` for a reason. `source: "vendor"` is a Yahoo
  Finance summary — say so ("Yahoo reports a 0.05% expense ratio as of
  today"). `source: "filing"` can be stated as fact with its URL.
  `source: "computed"` must name its inputs.
- **A prospectus outranks a vendor summary.** When a memo turns on the fee,
  confirm the vendor figure against the prospectus via
  `search_fund_filings`. If they disagree, report both and say which
  document you'd trust.
- **Confirm a retrieved passage names the fund.** `search_fund_filings`
  reads trust-level documents covering many sibling funds; its
  `scope_warning` says so. A passage about "the Fund" in a Vanguard Index
  Funds prospectus may be about a different series. If a passage doesn't
  name the fund or its series, don't cite it as that fund's.
- **A null is an answer.** Tracking difference is permanently null;
  replication method and securities lending are prospectus-only. Report
  what came back null and why. Never fill a null from memory.
- **Never promise a return or predict performance.** No "will outperform",
  no expected annual return, no "guaranteed". A Stop hook blocks this.
- **Holdings are stale by construction.** N-PORT covers a quarter-end and
  is filed up to 60 days later. Always state the as-of date; never call
  them current holdings.
- **Quoted currency is not currency exposure.** VXUS is quoted in USD and
  holds assets denominated in dozens of currencies. Say which you mean.
- **Never give tax or legal advice.** You may report what a prospectus says
  about distributions or tax treatment, cited. You may not tell the user
  what it means for their situation.
- **Ask when the ticker is ambiguous.** The registry returns
  `not_a_fund`, `not_covered`, or `unknown` with a reason — surface it
  verbatim and ask, rather than answering about a fund you guessed at. Note
  that some tickers collide across markets: VUSA resolves to a US fund in
  Tidal Trust III, and is *not* Vanguard's LSE-listed S&P 500 UCITS. If the
  registrant name doesn't match what the user seems to mean, say so and ask.
  This project covers **US-domiciled funds only**.

## Steps

1. **Resolve the fund and confirm identity.** Call `get_fund_profile`. Check
   the `status` first. If it isn't `ok`, stop and report the reason — that
   is the answer. Read back the fund's real name and registrant so the user
   can catch a wrong ticker immediately.

2. **Get the mandate from the prospectus.** Call `search_fund_filings` with
   a query about the objective and benchmark ("investment objective
   benchmark index the fund seeks to track"). This is what grounds sections
   1 and 2 of the memo. Confirm the passage names the fund.

3. **Get the exposure.** Use the profile's sector weights, top holdings, and
   top-10 concentration. For geographic exposure and full holdings, call
   `compute_fund_overlap` — its underlying N-PORT data carries country
   weights and the complete holdings list, filing-sourced.

4. **If the portfolio is in scope, compute overlap.** Call
   `compute_fund_overlap` whenever the user holds positions and is weighing
   a fund, or asks what it adds. This is the analysis they can't easily get
   elsewhere; lead with it when it's material.

   **Pick the right one of the two overlap tools.** `compute_fund_overlap`
   is for a fund being *considered* — "if I add VOO, how much of it do I
   already own?". `compute_true_exposure` is for the account as it *already
   is* — "counting through the funds I hold, what am I actually exposed
   to?". A question about whether the account is diversified, or where its
   real concentration sits, wants `compute_true_exposure`; a question about
   a candidate fund wants `compute_fund_overlap`. Both are filing-sourced
   and both carry per-fund as-of dates that must be stated.

5. **Find the alternatives.** Call `compare_funds` with the fund and its
   obvious same-mandate peers (S&P 500: VOO, IVV, SPLG; total international:
   VXUS, IXUS; Nasdaq-100: QQQ, QQQM). Report ties as ties.

6. **Search for the risks in the prospectus.** A second
   `search_fund_filings` call on principal risks, securities lending, or
   replication, depending on what the memo needs. Risks must be cited, not
   recalled.

7. **Write the memo.** The structure below. Every claim carries its source.

## Memo structure

```
## <FUND> — due-diligence memo
One line: what it is, its registrant, and its as-of caveats.

### 1. Mandate
Objective, benchmark index, domicile, quoted currency, exchange,
distribution policy. Cited to the prospectus.

### 2. Cost and structure
Expense ratio (vendor figure and prospectus figure), turnover, net assets,
replication method, securities lending, tracking difference. State the
nulls and why.

### 3. Exposure
Sector weights, country weights, top-10 holdings and concentration,
holdings count. Each with source and as-of date.

### 4. Risks and where this underperforms
Cited principal risks, plus the concrete scenarios in which this fund does
badly — concentration, currency, single-country weight, index construction.

### 5. Portfolio fit and what it does NOT give you
What exposure the fund adds; what it explicitly excludes. Overlap with
current holdings, with its as-of date.

### 6. Comparable alternatives
Same-mandate funds on cost, scale, concentration. Ties reported as ties.

### 7. What would make me avoid this fund
Concrete, checkable disqualifiers tied to the evidence above — not a
rating, not a directional call.
```

## Worked shape (VOO, abbreviated)

> **Mandate.** Vanguard S&P 500 ETF, a series of Vanguard Index Funds
> (CIK 0000036405, series S000002839), US-domiciled, quoted in USD on
> NYSE Arca. Tracks the S&P 500 — per the statutory prospectus filed
> 2026-02-27 [485BPOS URL].
>
> **Cost.** Yahoo reports a 0.03% expense ratio as of 2026-08-09 (vendor
> summary); the prospectus states [confirm via search_fund_filings].
> Turnover 2%. Net assets ~$487bn. Tracking difference: unavailable —
> it requires the index's total return, which no free source provides, so
> it is not reported rather than estimated.
>
> **Exposure.** 519 holdings as of 2026-03-31 (N-PORT, [URL]); top-10 at
> 36.5%; 100% US-domiciled issuers. That last figure is the point: this is
> a single-country fund.
>
> **Portfolio fit.** 14.6% of VOO's portfolio as of 2026-03-31 is in
> companies already held directly (AAPL 6.7%, MSFT 4.9%, XOM 1.3%, JNJ
> 1.1%, PLTR 0.6%, NKE 0.1%) — computed from the account fixture and the
> N-PORT filing. Adding it concentrates further into existing positions
> rather than diversifying away from them.
>
> **What it does not give you.** No ex-US exposure, no small caps, no
> bonds.
>
> **What would make me avoid it.** [Cited, checkable disqualifiers.]

Note what that example never says: whether to own it.
