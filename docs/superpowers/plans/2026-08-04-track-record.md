# Track Record & Alert Store Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Persist every research note and the dated view it states, then surface
those views as a Track Record page that shows which calls held up — plus an
alert store that captures price-watch conditions for a later watcher.

**Architecture:** `SessionStore` gains view fields and note persistence. A
second lightweight model call extracts the structured view after the note is
final, following the existing `_enforce_safety` pattern rather than changing
the agent loop's shape. A new web tab reads the ledger and compares each
recorded `view_price` against current price history. Alert conditions are
stored as JSON and managed through three tools registered in the shared
`tool_router`.

**Tech Stack:** Python 3.14, FastAPI, Anthropic SDK, yfinance, vanilla JS
(no build step), pytest.

## Global Constraints

- No build step in `web/` — vanilla JS, self-contained, responsive.
- Every displayed price carries its as-of time. A price is market data, never
  a filing fact.
- `runs.jsonl` and `alerts_fired.jsonl` are append-only — never edited in place.
- New ledger keys only; existing rows must stay readable with defaults.
- Ratings are the three values `bullish` | `neutral` | `bearish`, or `null`.
- Three themes (Terminal, Paper, Microfilm) must all render new UI correctly.
- Run `.venv/bin/python -m pytest tests/ -q` and `.venv/bin/python -m evals.run`
  after each task.

---

## File Structure

| File | Responsibility |
|---|---|
| `src/state/session_store.py` (modify) | ledger schema + note persistence |
| `backend/app.py` (modify) | call view extraction, pass to `finish_run` |
| `backend/view_extract.py` (create) | second-pass structured view extraction |
| `src/state/track_record.py` (create) | join ledger views to price outcomes |
| `backend/app.py` (modify) | `GET /api/track-record` endpoint |
| `web/app.js`, `index.html`, `style.css` (modify) | Track Record tab |
| `src/tools/alerts.py` (create) | alert store CRUD |
| `src/tool_router.py` (modify) | register three alert tools |
| `tests/test_session_store.py` (modify) | ledger + persistence tests |
| `tests/test_view_extract.py` (create) | extraction parsing tests |
| `tests/test_track_record.py` (create) | outcome computation tests |
| `tests/test_alerts.py` (create) | alert store tests |

---

### Task 1: Ledger records views and persists notes

**Files:**
- Modify: `src/state/session_store.py:31-62`
- Test: `tests/test_session_store.py`

**Interfaces:**
- Produces: `SessionStore.finish_run(note_text=None, view=None) -> dict`
  where `view` is `{"rating": str|None, "tickers": list[str],
  "view_price": dict[str, float], "change_my_mind": list[str]}`.
  Writes note markdown to `data/notes/<run_id>.md` and stores the relative
  path in the record's `note_path`. Adds `timestamp` (UTC ISO-8601) and
  `view` keys to every record.

- [ ] **Step 1: Write the failing test**

```python
import json
from pathlib import Path
from src.state.session_store import SessionStore


def test_finish_run_persists_note_and_view(tmp_path):
    store = SessionStore(store_path=tmp_path / "runs.jsonl")
    store.start_run("run-1", "How does NVDA look?")
    record = store.finish_run(
        note_text="## View\n\nBullish on execution.",
        view={
            "rating": "bullish",
            "tickers": ["NVDA"],
            "view_price": {"NVDA": 180.0},
            "change_my_mind": ["falls >15% with no filing-level reason"],
        },
    )

    assert record["view"]["rating"] == "bullish"
    assert record["view"]["tickers"] == ["NVDA"]
    assert record["view"]["view_price"]["NVDA"] == 180.0
    assert record["timestamp"].endswith("Z")

    note_file = (tmp_path / "runs.jsonl").parent / record["note_path"]
    assert note_file.read_text() == "## View\n\nBullish on execution."


def test_finish_run_without_view_still_writes_row(tmp_path):
    store = SessionStore(store_path=tmp_path / "runs.jsonl")
    store.start_run("run-2", "what is a 10-K?")
    record = store.finish_run()

    assert record["view"]["rating"] is None
    assert record["note_path"] is None


def test_old_rows_without_view_are_readable(tmp_path):
    path = tmp_path / "runs.jsonl"
    path.write_text(json.dumps({"run_id": "old", "question": "q",
                                "tool_calls": [], "citations": [],
                                "note_path": None}) + "\n")
    store = SessionStore(store_path=path)
    assert store.recent_runs(1)[0]["run_id"] == "old"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_session_store.py -v`
Expected: FAIL — `finish_run()` takes no `note_text` / `view` arguments.

- [ ] **Step 3: Implement**

In `src/state/session_store.py`, add near the top:

```python
from datetime import datetime, timezone

EMPTY_VIEW: dict[str, Any] = {
    "rating": None,
    "tickers": [],
    "view_price": {},
    "change_my_mind": [],
}
```

Replace `finish_run` (currently lines 54-62) with:

```python
    def finish_run(
        self,
        note_text: str | None = None,
        view: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if self._current_run is None:
            raise RuntimeError("finish_run called before start_run")

        record = self._current_run
        record["timestamp"] = (
            datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
        )
        record["view"] = {**EMPTY_VIEW, **(view or {})}

        if note_text:
            notes_dir = self._path.parent.parent / "notes"
            notes_dir.mkdir(parents=True, exist_ok=True)
            note_file = notes_dir / f"{record['run_id']}.md"
            note_file.write_text(note_text, encoding="utf-8")
            record["note_path"] = str(note_file.relative_to(self._path.parent))

        with open(self._path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record) + "\n")
        self._current_run = None
        return record
```

Add two readers used by later tasks:

```python
    def recorded_views(self) -> list[dict[str, Any]]:
        """Every run that recorded a rating, oldest first."""
        return [
            r for r in self.recent_runs(n=10_000)
            if (r.get("view") or {}).get("rating")
        ]

    def current_tool_calls(self) -> list[dict[str, Any]]:
        """Tool calls recorded so far in the open run."""
        if self._current_run is None:
            return []
        return list(self._current_run["tool_calls"])
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_session_store.py -v`
Expected: PASS.

- [ ] **Step 5: Confirm nothing else broke**

Run: `.venv/bin/python -m pytest tests/ -q`
Expected: all pass. `backend/app.py` calls `finish_run()` with no arguments,
which still works because both parameters default to `None`.

- [ ] **Step 6: Add `data/notes/` to `.gitignore`**

Notes are personal research output, not source. Append to `.gitignore`:

```
data/notes/
```

- [ ] **Step 7: Commit**

```bash
git add src/state/session_store.py tests/test_session_store.py .gitignore
git commit -m "feat: persist research notes and dated views in the ledger"
```

---

### Task 2: Extract the structured view from a finished note

**Files:**
- Create: `backend/view_extract.py`
- Create: `tests/test_view_extract.py`
- Modify: `backend/app.py:103-107`

**Interfaces:**
- Consumes: `SessionStore.finish_run(note_text, view)` from Task 1.
- Produces: `extract_view(client, note_text, quotes) -> dict` returning the
  same four-key shape Task 1 accepts. `quotes` is `dict[str, float]` mapping
  ticker to the price observed during the run; `extract_view` never fetches
  prices itself.
- Produces: `tickers_from_tool_calls(tool_calls) -> list[str]`.

- [ ] **Step 1: Write the failing test**

```python
from backend.view_extract import tickers_from_tool_calls, parse_view_json


def test_tickers_pulled_from_recorded_calls():
    calls = [
        {"tool": "compute_metrics", "args": {"ticker": "nvda"}},
        {"tool": "get_quote", "args": {"ticker": "NVDA"}},
        {"tool": "get_portfolio_snapshot", "args": {}},
    ]
    assert tickers_from_tool_calls(calls) == ["NVDA"]


def test_parse_view_json_reads_fenced_payload():
    raw = '```json\n{"rating": "bullish", "change_my_mind": ["margin < 70%"]}\n```'
    parsed = parse_view_json(raw)
    assert parsed["rating"] == "bullish"
    assert parsed["change_my_mind"] == ["margin < 70%"]


def test_parse_view_json_rejects_unknown_rating():
    parsed = parse_view_json('{"rating": "strong conviction", "change_my_mind": []}')
    assert parsed["rating"] is None


def test_parse_view_json_survives_garbage():
    assert parse_view_json("no json here")["rating"] is None
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_view_extract.py -v`
Expected: FAIL — `ModuleNotFoundError: backend.view_extract`.

- [ ] **Step 3: Implement `backend/view_extract.py`**

```python
"""Second-pass extraction of the structured view from a finished note.

The agent loop returns prose. The Track Record page needs a dated, machine
readable rating. Rather than regexing the note — which silently yields nulls
the moment phrasing drifts — a small follow-up model call reads the finished
note and returns JSON. This mirrors how ``_enforce_safety`` already makes a
second pass over the final text.

Extraction never invents a price: ``view_price`` is passed in from quotes
actually observed during the run, so a recorded view price always traces to
a real ``get_quote`` call.
"""

from __future__ import annotations

import json
import re
from typing import Any

VALID_RATINGS = {"bullish", "neutral", "bearish"}

EXTRACT_PROMPT = """Read this research note and return ONLY a JSON object:

{"rating": "bullish" | "neutral" | "bearish" | null,
 "change_my_mind": ["<each falsifiable condition the note states>"]}

Use the note's stated View section. If the note states no view, use null.
Copy conditions verbatim from the note. Invent nothing.

NOTE:
"""


def tickers_from_tool_calls(tool_calls: list[dict[str, Any]]) -> list[str]:
    """Distinct uppercase tickers that appeared in recorded call arguments."""
    seen: list[str] = []
    for call in tool_calls:
        ticker = (call.get("args") or {}).get("ticker")
        if isinstance(ticker, str) and ticker.strip():
            upper = ticker.strip().upper()
            if upper not in seen:
                seen.append(upper)
    return seen


def parse_view_json(raw: str) -> dict[str, Any]:
    """Parse the extraction reply, defaulting to an empty view on anything odd."""
    empty = {"rating": None, "change_my_mind": []}
    match = re.search(r"\{.*\}", raw, re.DOTALL)
    if not match:
        return empty
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError:
        return empty

    rating = data.get("rating")
    if rating not in VALID_RATINGS:
        rating = None

    conditions = data.get("change_my_mind")
    if not isinstance(conditions, list):
        conditions = []
    conditions = [str(c) for c in conditions if str(c).strip()]

    return {"rating": rating, "change_my_mind": conditions}


def extract_view(
    client: Any,
    note_text: str,
    tool_calls: list[dict[str, Any]],
    quotes: dict[str, float],
    model: str,
) -> dict[str, Any]:
    """Return the four-key view dict for ``SessionStore.finish_run``."""
    try:
        reply = client.messages.create(
            model=model,
            max_tokens=512,
            messages=[{"role": "user", "content": EXTRACT_PROMPT + note_text}],
        )
        raw = "".join(b.text for b in reply.content if b.type == "text")
        parsed = parse_view_json(raw)
    except Exception:
        # Extraction is best-effort metadata. A failure must never break the
        # research answer the user actually asked for.
        parsed = {"rating": None, "change_my_mind": []}

    tickers = tickers_from_tool_calls(tool_calls)
    return {
        "rating": parsed["rating"],
        "tickers": tickers,
        "view_price": {t: quotes[t] for t in tickers if t in quotes},
        "change_my_mind": parsed["change_my_mind"],
    }
```

- [ ] **Step 4: Run to verify the tests pass**

Run: `.venv/bin/python -m pytest tests/test_view_extract.py -v`
Expected: PASS.

- [ ] **Step 5: Capture observed quotes in the agent loop**

In `backend/app.py`, inside `run_research`, add before the iteration loop
(after `tool_calls_made: list[str] = []` on line 92):

```python
    observed_quotes: dict[str, float] = {}
```

Immediately after the `result = tool_router.call_tool(...)` try/except block
(after line 123), add:

```python
            # The ledger's tool_calls list has never been populated on this
            # code path — only the MCP server recorded provenance. Without
            # this, extraction sees no tickers and every view lands empty.
            store.record_tool_call(block.name, block.input, _summarize(result))

            if block.name == "get_quote" and isinstance(result, dict):
                ticker = str(block.input.get("ticker", "")).upper()
                price = result.get("price")
                if ticker and isinstance(price, (int, float)):
                    observed_quotes[ticker] = float(price)
```

`get_quote` returns the keys `ticker`, `price`, `previous_close`, `change`,
`change_pct` — there is no `last_price`.

Add this helper near `_to_text` in `backend/app.py`; full tool payloads would
bloat every ledger row:

```python
def _summarize(result: Any, limit: int = 400) -> Any:
    """Compact a tool result for the ledger without storing the whole payload."""
    text = _to_text(result)
    return text if len(text) <= limit else text[:limit] + "…"
```

- [ ] **Step 6: Wire extraction into the finish path**

Replace line 106 (`store.finish_run()`) with:

```python
            view = extract_view(
                client,
                final_text,
                store.current_tool_calls(),
                observed_quotes,
                MODEL,
            )
            store.finish_run(note_text=final_text, view=view)
```

Add the import at the top of `backend/app.py`:

```python
from backend.view_extract import extract_view
```

- [ ] **Step 7: Verify the whole suite still passes**

Run: `.venv/bin/python -m pytest tests/ -q && .venv/bin/python -m evals.run`
Expected: all tests pass; all five eval thresholds PASS.

- [ ] **Step 8: Commit**

```bash
git add backend/view_extract.py tests/test_view_extract.py backend/app.py
git commit -m "feat: extract structured view metadata after each research note"
```

---

### Task 3: Compute outcomes for recorded views

**Files:**
- Create: `src/state/track_record.py`
- Create: `tests/test_track_record.py`

**Interfaces:**
- Consumes: `SessionStore.recorded_views()` from Task 1.
- Produces: `score_views(views, current_prices, now, min_days=7) -> dict` with
  shape `{"summary": {"total": int, "resolved": int, "correct": int},
  "rows": [...]}`. Each row is `{"run_id", "timestamp", "ticker", "rating",
  "view_price", "current_price", "pct_change", "status", "note_path"}` where
  `status` is `"correct"` | `"incorrect"` | `"pending"`.

**Scoring rule:** a `bullish` view is correct when `pct_change > 0`, `bearish`
when `pct_change < 0`. `neutral` is correct when `abs(pct_change) <= 5`. A view
younger than `min_days` is `"pending"` regardless — a call needs time before
it can be graded.

- [ ] **Step 1: Write the failing test**

```python
from datetime import datetime, timedelta, timezone
from src.state.track_record import score_views

NOW = datetime(2026, 8, 4, tzinfo=timezone.utc)


def _view(rating, price, days_ago, ticker="NVDA", run_id="r1"):
    ts = (NOW - timedelta(days=days_ago)).isoformat().replace("+00:00", "Z")
    return {
        "run_id": run_id,
        "timestamp": ts,
        "note_path": f"../notes/{run_id}.md",
        "view": {
            "rating": rating,
            "tickers": [ticker],
            "view_price": {ticker: price},
            "change_my_mind": [],
        },
    }


def test_bullish_view_that_rose_is_correct():
    result = score_views([_view("bullish", 100.0, 30)], {"NVDA": 120.0}, NOW)
    row = result["rows"][0]
    assert row["status"] == "correct"
    assert row["pct_change"] == 20.0
    assert result["summary"] == {"total": 1, "resolved": 1, "correct": 1}


def test_bearish_view_that_rose_is_incorrect():
    result = score_views([_view("bearish", 100.0, 30)], {"NVDA": 120.0}, NOW)
    assert result["rows"][0]["status"] == "incorrect"
    assert result["summary"]["correct"] == 0


def test_recent_view_is_pending_even_if_it_moved():
    result = score_views([_view("bullish", 100.0, 2)], {"NVDA": 200.0}, NOW)
    assert result["rows"][0]["status"] == "pending"
    assert result["summary"] == {"total": 1, "resolved": 0, "correct": 0}


def test_neutral_view_within_five_percent_is_correct():
    result = score_views([_view("neutral", 100.0, 30)], {"NVDA": 103.0}, NOW)
    assert result["rows"][0]["status"] == "correct"


def test_missing_current_price_is_pending():
    result = score_views([_view("bullish", 100.0, 30)], {}, NOW)
    assert result["rows"][0]["status"] == "pending"


def test_view_without_recorded_price_is_skipped():
    v = _view("bullish", 100.0, 30)
    v["view"]["view_price"] = {}
    assert score_views([v], {"NVDA": 120.0}, NOW)["rows"] == []
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_track_record.py -v`
Expected: FAIL — `ModuleNotFoundError: src.state.track_record`.

- [ ] **Step 3: Implement `src/state/track_record.py`**

```python
"""Score previously stated views against what prices actually did.

This is the one thing a general research tool cannot do: it never took a
position, so it has nothing to be graded on. Because every note here states a
dated rating into an append-only ledger, those calls can be lined up against
outcomes afterward.

Scoring is deliberately crude and honest about it — direction only, over a
minimum holding window, against a market price with its own as-of time. It is
a record of what was said and what happened, not a performance claim.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

NEUTRAL_BAND_PCT = 5.0


def _parse_ts(raw: str) -> datetime:
    return datetime.fromisoformat(raw.replace("Z", "+00:00"))


def _status(rating: str, pct_change: float) -> str:
    if rating == "bullish":
        return "correct" if pct_change > 0 else "incorrect"
    if rating == "bearish":
        return "correct" if pct_change < 0 else "incorrect"
    return "correct" if abs(pct_change) <= NEUTRAL_BAND_PCT else "incorrect"


def score_views(
    views: list[dict[str, Any]],
    current_prices: dict[str, float],
    now: datetime,
    min_days: int = 7,
) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []

    for run in views:
        view = run.get("view") or {}
        rating = view.get("rating")
        if rating not in {"bullish", "neutral", "bearish"}:
            continue

        for ticker, view_price in (view.get("view_price") or {}).items():
            if not view_price:
                continue

            current = current_prices.get(ticker)
            stated_at = _parse_ts(run["timestamp"])
            mature = now - stated_at >= timedelta(days=min_days)

            if current is None or not mature:
                pct_change = None
                status = "pending"
            else:
                pct_change = round((current - view_price) / view_price * 100, 1)
                status = _status(rating, pct_change)

            rows.append({
                "run_id": run["run_id"],
                "timestamp": run["timestamp"],
                "ticker": ticker,
                "rating": rating,
                "view_price": view_price,
                "current_price": current,
                "pct_change": pct_change,
                "status": status,
                "note_path": run.get("note_path"),
            })

    resolved = [r for r in rows if r["status"] != "pending"]
    return {
        "summary": {
            "total": len(rows),
            "resolved": len(resolved),
            "correct": sum(1 for r in resolved if r["status"] == "correct"),
        },
        "rows": rows,
    }
```

- [ ] **Step 4: Run to verify the tests pass**

Run: `.venv/bin/python -m pytest tests/test_track_record.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/state/track_record.py tests/test_track_record.py
git commit -m "feat: score stated views against realized price moves"
```

---

### Task 4: Track Record API endpoint

**Files:**
- Modify: `backend/app.py` (add endpoint near the existing `/api/ask` routes)
- Test: `tests/test_track_record_api.py` (create)

**Interfaces:**
- Consumes: `score_views` (Task 3), `SessionStore.recorded_views` (Task 1).
- Produces: `GET /api/track-record` returning the `score_views` payload plus
  `"as_of"` (UTC ISO-8601 string) so the UI can stamp its prices.

- [ ] **Step 1: Write the failing test**

```python
from fastapi.testclient import TestClient
from backend.app import app


def test_track_record_endpoint_returns_summary_shape():
    client = TestClient(app)
    body = client.get("/api/track-record").json()
    assert set(body) >= {"summary", "rows", "as_of"}
    assert set(body["summary"]) == {"total", "resolved", "correct"}
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_track_record_api.py -v`
Expected: FAIL — 404, route not registered.

- [ ] **Step 3: Implement the endpoint in `backend/app.py`**

```python
@app.get("/api/track-record")
def track_record() -> dict[str, Any]:
    from datetime import datetime, timezone

    from src.state.track_record import score_views
    from src.tools.quotes import get_quote

    store = get_default_store()
    views = store.recorded_views()

    tickers = {t for r in views for t in (r.get("view") or {}).get("view_price", {})}
    prices: dict[str, float] = {}
    for ticker in tickers:
        try:
            quote = get_quote(ticker)
            if isinstance(quote.get("price"), (int, float)):
                prices[ticker] = float(quote["price"])
        except Exception:
            # A quote failure degrades a row to "pending", never a 500.
            continue

    now = datetime.now(timezone.utc)
    payload = score_views(views, prices, now)
    payload["as_of"] = now.isoformat(timespec="seconds").replace("+00:00", "Z")
    return payload
```

- [ ] **Step 4: Run to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_track_record_api.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app.py tests/test_track_record_api.py
git commit -m "feat: add track-record API endpoint"
```

---

### Task 5: Track Record page in the web UI

**Files:**
- Modify: `web/index.html`, `web/app.js`, `web/style.css`

**Interfaces:**
- Consumes: `GET /api/track-record` (Task 4).

**Design constraints:** reuse the existing Ledger & Stamp tokens — no new
colors outside the token set. Must render correctly in Terminal, Paper, and
Microfilm. The empty state is a designed state, not an accident: this page
ships with zero rows and must look deliberate.

- [ ] **Step 1: Add the nav control and container to `index.html`**

Next to the existing masthead controls, add:

```html
<button id="track-record-toggle" class="masthead-btn">Track Record</button>
```

Before the closing main container, add:

```html
<section id="track-record" class="track-record" hidden>
  <header class="tr-header">
    <h2>Track Record</h2>
    <p id="tr-summary" class="tr-summary">—</p>
  </header>
  <div id="tr-rows" class="tr-rows"></div>
  <p id="tr-asof" class="tr-asof"></p>
</section>
```

- [ ] **Step 2: Render the page in `app.js`**

```javascript
const RATING_MARK = { bullish: "▲", neutral: "■", bearish: "▼" };

async function loadTrackRecord() {
  const panel = document.getElementById("track-record");
  const rowsEl = document.getElementById("tr-rows");
  const summaryEl = document.getElementById("tr-summary");
  const asOfEl = document.getElementById("tr-asof");

  rowsEl.innerHTML = '<p class="tr-loading">Loading…</p>';
  panel.hidden = false;

  let data;
  try {
    data = await (await fetch("/api/track-record")).json();
  } catch (err) {
    rowsEl.innerHTML = '<p class="tr-empty">Could not load the ledger.</p>';
    return;
  }

  const { total, resolved, correct } = data.summary;
  summaryEl.textContent = total
    ? `${total} view${total === 1 ? "" : "s"} · ${resolved} resolved · ${correct} correct`
    : "";

  if (!data.rows.length) {
    rowsEl.innerHTML =
      '<p class="tr-empty">No views recorded yet.<br>' +
      "Ask for a research note and the view it states will be logged here, " +
      "dated, and scored once it has had time to play out.</p>";
    asOfEl.textContent = "";
    return;
  }

  rowsEl.innerHTML = data.rows
    .slice()
    .reverse()
    .map((r) => {
      const move =
        r.pct_change === null
          ? "—"
          : `${r.pct_change > 0 ? "+" : ""}${r.pct_change}%`;
      const priceNow = r.current_price === null ? "—" : `$${r.current_price.toFixed(2)}`;
      return `
        <article class="tr-row tr-${r.status}">
          <span class="tr-ticker">${r.ticker}</span>
          <span class="tr-rating">${RATING_MARK[r.rating]} ${r.rating}</span>
          <span class="tr-date">${r.timestamp.slice(0, 10)}</span>
          <span class="tr-price">$${r.view_price.toFixed(2)} → ${priceNow}</span>
          <span class="tr-move">${move}</span>
          <span class="tr-status">${r.status}</span>
        </article>`;
    })
    .join("");

  asOfEl.textContent = `Prices as of ${data.as_of}. Direction only, scored after 7 days.`;
}

document
  .getElementById("track-record-toggle")
  .addEventListener("click", loadTrackRecord);
```

- [ ] **Step 3: Style it in `style.css`**

```css
.track-record { margin-top: 2rem; }
.tr-summary { color: var(--fg-muted); font-size: 0.9rem; }
.tr-rows { display: flex; flex-direction: column; gap: 0.25rem; }
.tr-row {
  display: grid;
  grid-template-columns: 5rem 8rem 6rem 1fr 5rem 5rem;
  gap: 0.75rem;
  padding: 0.5rem 0.6rem;
  border-left: 3px solid var(--fg-muted);
  align-items: baseline;
}
.tr-correct   { border-left-color: var(--accent-positive); }
.tr-incorrect { border-left-color: var(--accent-negative); }
.tr-pending   { border-left-color: var(--fg-muted); opacity: 0.75; }
.tr-ticker { font-weight: 600; }
.tr-status, .tr-date { color: var(--fg-muted); font-size: 0.85rem; }
.tr-empty { color: var(--fg-muted); padding: 2rem 0; line-height: 1.6; }
.tr-asof { color: var(--fg-muted); font-size: 0.8rem; margin-top: 1rem; }

@media (max-width: 640px) {
  .tr-row { grid-template-columns: 1fr 1fr; }
}
```

If `--accent-positive` / `--accent-negative` are not already defined in the
token block, add them per theme alongside the existing tokens. Do not
introduce hard-coded hex values in the rules above.

- [ ] **Step 4: Verify**

Run: `node --check web/app.js` (expect no output), then load
`http://localhost:8000`, click **Track Record**, and confirm: the empty state
reads as designed, and the layout holds in all three themes and at 640px.

- [ ] **Step 5: Commit**

```bash
git add web/index.html web/app.js web/style.css
git commit -m "feat: add Track Record page"
```

---

### Task 6: Alert store and management tools

**Files:**
- Create: `src/tools/alerts.py`
- Create: `tests/test_alerts.py`
- Modify: `src/tool_router.py`

**Interfaces:**
- Produces: `add_price_alert(ticker, direction, pct, baseline="prev_close") -> dict`,
  `list_price_alerts() -> dict`, `remove_price_alert(alert_id) -> dict`.
  Storage is `data/portfolio/alerts.json`, a JSON list.

**Scope:** conditions are stored and listed only. Nothing evaluates or fires
them — the watcher is phase 2. This exists now so real conditions accumulate
from day one.

- [ ] **Step 1: Write the failing test**

```python
import pytest
from src.tools import alerts as alerts_mod


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(alerts_mod, "ALERTS_PATH", tmp_path / "alerts.json")
    return alerts_mod


def test_add_then_list(store):
    created = store.add_price_alert("nvda", "down", 5.0)
    assert created["alert"]["ticker"] == "NVDA"
    assert created["alert"]["direction"] == "down"
    assert store.list_price_alerts()["alerts"][0]["id"] == created["alert"]["id"]


def test_remove(store):
    created = store.add_price_alert("NVDA", "down", 5.0)
    store.remove_price_alert(created["alert"]["id"])
    assert store.list_price_alerts()["alerts"] == []


def test_remove_unknown_id_reports_cleanly(store):
    assert store.remove_price_alert("nope")["removed"] is False


def test_rejects_bad_direction(store):
    with pytest.raises(ValueError):
        store.add_price_alert("NVDA", "sideways", 5.0)


def test_rejects_non_positive_pct(store):
    with pytest.raises(ValueError):
        store.add_price_alert("NVDA", "down", 0)


def test_list_on_missing_file_is_empty(store):
    assert store.list_price_alerts()["alerts"] == []
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_alerts.py -v`
Expected: FAIL — `ImportError: cannot import name 'alerts'`.

- [ ] **Step 3: Implement `src/tools/alerts.py`**

```python
"""Personal price-watch conditions.

Like the watchlist, this is deliberately writable: a condition you want to be
told about is a personal to-do, not account data and not an execution path.
Nothing here reaches a broker, and nothing here acts — this module only
records what you asked to be notified about.

Storing conditions now, ahead of the watcher that evaluates them, means real
conditions accumulate from day one instead of being invented later.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ALERTS_PATH = Path(__file__).resolve().parents[2] / "data" / "portfolio" / "alerts.json"

VALID_DIRECTIONS = {"down", "up"}
VALID_BASELINES = {"prev_close", "7d", "30d", "view_price"}


def _load() -> list[dict[str, Any]]:
    if not ALERTS_PATH.exists():
        return []
    try:
        return json.loads(ALERTS_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []


def _save(alerts: list[dict[str, Any]]) -> None:
    ALERTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    ALERTS_PATH.write_text(json.dumps(alerts, indent=2) + "\n", encoding="utf-8")


def add_price_alert(
    ticker: str,
    direction: str,
    pct: float,
    baseline: str = "prev_close",
) -> dict[str, Any]:
    if direction not in VALID_DIRECTIONS:
        raise ValueError(f"direction must be one of {sorted(VALID_DIRECTIONS)}")
    if baseline not in VALID_BASELINES:
        raise ValueError(f"baseline must be one of {sorted(VALID_BASELINES)}")
    if pct <= 0:
        raise ValueError("pct must be greater than zero")

    alert = {
        "id": uuid.uuid4().hex[:6],
        "ticker": ticker.strip().upper(),
        "direction": direction,
        "pct": float(pct),
        "baseline": baseline,
        "enabled": True,
        "created_at": datetime.now(timezone.utc)
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z"),
        "last_fired_at": None,
    }
    alerts = _load()
    alerts.append(alert)
    _save(alerts)
    return {
        "alert": alert,
        "note": "Condition saved. Alerts are not yet delivered — the watcher ships next.",
    }


def list_price_alerts() -> dict[str, Any]:
    return {"alerts": _load()}


def remove_price_alert(alert_id: str) -> dict[str, Any]:
    alerts = _load()
    remaining = [a for a in alerts if a["id"] != alert_id]
    if len(remaining) == len(alerts):
        return {"removed": False, "reason": f"No alert with id {alert_id}."}
    _save(remaining)
    return {"removed": True, "id": alert_id}
```

- [ ] **Step 4: Run to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_alerts.py -v`
Expected: PASS.

- [ ] **Step 5: Register the three tools in `src/tool_router.py`**

Follow the existing `add_to_watchlist` registration exactly — same schema
style, same dispatch entry. Mark all three `readOnlyHint: false` and
`openWorldHint: false`. Schemas:

```python
{
    "name": "add_price_alert",
    "description": (
        "Record a price condition to be notified about later (e.g. NVDA down 5% "
        "from the previous close). Saves the condition only; delivery is not yet "
        "implemented. Not an execution path — this project cannot act on prices."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "ticker": {"type": "string"},
            "direction": {"type": "string", "enum": ["down", "up"]},
            "pct": {"type": "number", "description": "Percent move, e.g. 5 for 5%."},
            "baseline": {
                "type": "string",
                "enum": ["prev_close", "7d", "30d", "view_price"],
                "description": "What the move is measured against.",
            },
        },
        "required": ["ticker", "direction", "pct"],
    },
},
{
    "name": "list_price_alerts",
    "description": "List the user's saved price-watch conditions.",
    "input_schema": {"type": "object", "properties": {}},
},
{
    "name": "remove_price_alert",
    "description": "Delete a saved price-watch condition by its id.",
    "input_schema": {
        "type": "object",
        "properties": {"alert_id": {"type": "string"}},
        "required": ["alert_id"],
    },
},
```

- [ ] **Step 6: Verify registration**

Run:
```bash
.venv/bin/python -c "
from src import tool_router
names = [s['name'] for s in tool_router.TOOL_SCHEMAS]
print(len(names), 'tools')
assert 'add_price_alert' in names and 'list_price_alerts' in names
print(tool_router.call_tool('list_price_alerts', {}))
"
```
Expected: `18 tools` and an empty alert list.

- [ ] **Step 7: Update `CLAUDE.md`**

In the tool table, add the three tools and change "Fifteen MCP tools" to
"Eighteen MCP tools". In the watchlist bullet under Hard Boundaries, note that
`data/portfolio/alerts.json` is writable for the same reason the watchlist is.
Do **not** add the monitoring amendment — nothing observes anything yet. That
lands with the watcher in phase 2.

- [ ] **Step 8: Full verification and commit**

```bash
.venv/bin/python -m pytest tests/ -q
.venv/bin/python -m evals.run
git add src/tools/alerts.py tests/test_alerts.py src/tool_router.py CLAUDE.md
git commit -m "feat: record price-watch conditions"
```

---

## Seeding (manual, after Task 2)

The Track Record page has no historical data — prior notes were never
persisted and the one surviving conversation file contains no view sections.
After Task 2 lands, generate 6–8 real research notes on tickers you actually
care about, each stating a view. These become the page's first rows.

Do not fabricate history. An invented track record is precisely the failure
this project's traceability rules exist to prevent.

## Phase 2 (not in this plan)

From `docs/superpowers/specs/2026-08-04-price-alerts-design.md`: the poller,
sustain windows, cooldowns, quiet hours, two-tier notification, the CLAUDE.md
monitoring amendment, and `/recheck`.
