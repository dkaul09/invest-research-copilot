# Price Alerts & Push Notifications — Design

Date: 2026-08-04
Status: approved, not yet implemented

## Problem

The copilot only speaks when spoken to. Both interfaces (web UI, Telegram)
are pull-only: you ask, it researches, it answers. If a holding moves
against a view you formed last month, nothing tells you.

A bare price alert is a commodity — every brokerage app sends those, free
and faster. The value here is not the trigger, it is the payload: an alert
that arrives carrying the view you previously wrote and the condition you
said would change your mind. That is something a general research tool
cannot send, because it never took a position and never knew yours.

## Guiding principle

**The trigger is dumb. The message is smart.**

Threshold crossing is simple arithmetic on a quote. The differentiation
lives entirely in what the notification says once it fires.

## Boundary amendment (prerequisite)

CLAUDE.md currently states the tool "does not run unattended, does not
monitor the market, and does not take action." A scheduled poller violates
the first two literally.

The amendment is narrow and must be made before any scheduler code lands:

> The alert watcher may observe prices on a schedule and notify the user.
> It may never act. Notification is not execution. The watcher's only tool
> access is `get_quote`; it can reach no research, write, or account tool,
> and no execution-capable tool exists in this project to reach.

This preserves the real boundary (nothing acts) while dropping an
over-broad clause (nothing observes) that the feature needs.

## Components

### 1. Alert store — `data/portfolio/alerts.json`

Same posture as `watchlist.json`: a small, user-owned, writable JSON file.
Tracking a price is not account data and not an execution path.

```json
[
  {
    "id": "a1b2c3",
    "ticker": "NVDA",
    "direction": "down",
    "pct": 5.0,
    "baseline": "prev_close",
    "sustain_minutes": 15,
    "cooldown_hours": 12,
    "enabled": true,
    "created_at": "2026-08-04T18:40:00Z",
    "last_fired_at": null
  }
]
```

Field notes:

- `direction`: `"down"` | `"up"`.
- `baseline` — what the move is measured against:
  - `prev_close` — yesterday's official close
  - `7d` / `30d` — close N calendar days back, via `get_price_history`
  - `view_price` — the price when the user last recorded a view on this
    ticker, read from the ledger. Enables thesis-breach alerts.
- `sustain_minutes` — the condition must hold across consecutive polls for
  this long before firing. Suppresses momentary wicks.
- `cooldown_hours` — minimum gap between firings of the same alert.

### 2. Evaluator — `src/alerts/evaluate.py`

One pure function, no network, no clock, no I/O:

```python
def evaluate(alerts, quotes, history, ledger, now) -> list[FiredAlert]
```

All time and market data arrive as arguments. This is where every unit test
points.

### 3. Poller — `src/alerts/watcher.py`

Runs on an interval during US market hours. Per cycle:

1. Collect enabled alerts, batch one `get_quote` per distinct ticker.
2. Call `evaluate(...)`.
3. Append each fired alert to `data/sessions/alerts_fired.jsonl`
   (append-only, never edited in place — same discipline as `runs.jsonl`).
4. Hand fired alerts to the notifier.
5. Persist `last_fired_at` and sustain-tracking state.

The watcher imports `get_quote` and nothing else from the tool layer.

### 4. Notifier — `send_alert()` in `telegram_bot.py`

Sends to `TELEGRAM_ALLOWED_CHAT_ID`. Splits at 4000 chars, reusing the
existing chunking. No new access-control surface: the bot already restricts
to a single chat id.

### 5. Alert management tools — `src/tools/alerts.py`

Registered in `src/tool_router.py`, which both interfaces and the MCP
server share. Adding them there yields web UI + Telegram + Claude Code with
no per-interface work.

| Tool | Purpose |
|---|---|
| `add_price_alert` | create a watch condition |
| `list_price_alerts` | show active alerts |
| `remove_price_alert` | delete one |

Writable, like `add_to_watchlist`, and for the same reason: a watch
condition is a personal to-do, not account or execution data.

### 6. Ledger extension — `data/sessions/runs.jsonl`

Current rows carry only `citations`, `note_path`, `question`, `run_id`,
`tool_calls`. `note_path` is null on recent rows and no view is recorded.

Add per run: `timestamp`, `tickers[]`, `rating`, `view_price`,
`change_my_mind[]`. New keys only — existing rows stay valid, readers
default missing fields.

This unlocks `baseline: "view_price"` and red-tier alerts. It is also the
substrate for future calibration work (scoring past views against what
actually happened), which is out of scope here.

## Notification tiers

| Tier | Condition | Behavior |
|---|---|---|
| 🔴 thesis breach | crossed a `change_my_mind` condition | push immediately, ignores quiet hours |
| 🟡 notable move | threshold on a held/watchlist name | push, suppressed during quiet hours |

**Quiet hours**: outside 09:30–16:00 ET on US market days. A yellow-tier
alert that fires outside that window is written to `alerts_fired.jsonl` but
not pushed. Since the poller only runs during market hours, this matters
only for pre/post-market ticks and holidays. Red tier always pushes.

Example red-tier payload:

```
🔴 NVDA — thesis condition met

Your note (2026-07-14) rated NVDA BULLISH at $180.00.
You wrote: "reconsider if it falls >15% without a
filing-level reason."  → now -16.0%.

$151.20, as of 2026-08-04 14:32 ET.
No new 10-K/10-Q since 2026-05-28.

/recheck NVDA to re-run the full note.
```

Every price carries its as-of time, per the existing market-data rule.

### `/recheck <TICKER>`

A Telegram command that re-runs `run_research` for the ticker and returns a
fresh note. Reuses the existing agent loop entirely.

## Build sequence

Forced by dependencies:

1. CLAUDE.md boundary amendment
2. Ledger extension (`runs.jsonl` schema + writer)
3. Alert store + `evaluate()` + tests
4. Management tools in `tool_router.py`
5. Poller
6. Telegram push — **yellow tier works here**
7. `view_price` baseline + red-tier payload
8. `/recheck`

## Testing

- `evaluate()`: table-driven — threshold unmet; met but not sustained; met
  within cooldown; each `baseline` variant; disabled alerts skipped; up and
  down directions; missing quote data.
- Store: round-trip add/list/remove, malformed file handling.
- Poller: injected fake quote source, asserts no network.
- Notifier: fake send, asserts chunking and tier formatting.
- `python -m evals.run` after, per project convention.

## Out of scope

- Multiple recipients — single user, `TELEGRAM_ALLOWED_CHAT_ID` suffices.
- Web UI for managing alerts — conversational management first; add later
  only if it proves annoying.
- Calibration scoring of past views — enabled by the ledger change, built
  separately.
- Intraday streaming — polling is sufficient at this cadence.
- Daily digest of routine moves — a third notification tier was considered
  and cut. Two tiers (act-now, worth-knowing) cover the need; a digest is a
  separate feature with its own scheduling and formatting questions.
