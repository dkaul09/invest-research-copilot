"""Session ledger: append-only, ordered replay, provenance lookup by ticker."""

from src.state.session_store import SessionStore


def test_runs_append_and_are_ordered(tmp_path):
    store = SessionStore(store_path=tmp_path / "runs.jsonl")

    store.start_run("run-1", "first question")
    store.record_tool_call("compute_metrics", {"ticker": "AAPL"}, {"ok": True})
    store.finish_run(note_path="notes/1.md")

    store.start_run("run-2", "second question")
    store.record_tool_call("compute_metrics", {"ticker": "MSFT"}, {"ok": True})
    store.finish_run(note_path="notes/2.md")

    runs = store.recent_runs(n=10)
    assert [r["run_id"] for r in runs] == ["run-1", "run-2"]


def test_finish_run_without_start_raises(tmp_path):
    store = SessionStore(store_path=tmp_path / "runs.jsonl")
    try:
        store.finish_run()
        assert False, "expected RuntimeError"
    except RuntimeError:
        pass


def test_provenance_for_finds_runs_touching_a_ticker(tmp_path):
    store = SessionStore(store_path=tmp_path / "runs.jsonl")

    store.start_run("run-1", "about AAPL")
    store.record_tool_call("compute_metrics", {"ticker": "AAPL"}, {"ok": True})
    store.finish_run()

    store.start_run("run-2", "about MSFT")
    store.record_tool_call("compute_metrics", {"ticker": "MSFT"}, {"ok": True})
    store.finish_run()

    provenance = store.provenance_for("AAPL")
    assert len(provenance) == 1
    assert provenance[0]["run_id"] == "run-1"


def test_citations_are_recorded_on_the_run():
    from pathlib import Path
    import tempfile

    with tempfile.TemporaryDirectory() as d:
        store = SessionStore(store_path=Path(d) / "runs.jsonl")
        store.start_run("run-1", "why did margins change")
        store.record_citation("NKE", "MD&A: Margin Discussion", "https://sec.gov/example")
        record = store.finish_run()
        assert record["citations"][0]["ticker"] == "NKE"


def test_recent_runs_on_empty_store_returns_empty_list(tmp_path):
    store = SessionStore(store_path=tmp_path / "runs.jsonl")
    assert store.recent_runs() == []


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
    import json
    path = tmp_path / "runs.jsonl"
    path.write_text(json.dumps({"run_id": "old", "question": "q",
                                "tool_calls": [], "citations": [],
                                "note_path": None}) + "\n")
    store = SessionStore(store_path=path)
    assert store.recent_runs(1)[0]["run_id"] == "old"


def test_finish_run_persists_note_and_view(tmp_path):
    store = SessionStore(store_path=tmp_path / "sessions" / "runs.jsonl")
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

    note_file = (tmp_path / "sessions") / record["note_path"]
    assert note_file.read_text() == "## View\n\nBullish on execution."


def test_finish_run_without_view_still_writes_row(tmp_path):
    store = SessionStore(store_path=tmp_path / "sessions" / "runs.jsonl")
    store.start_run("run-2", "what is a 10-K?")
    record = store.finish_run()

    assert record["view"]["rating"] is None
    assert record["note_path"] is None


def test_old_rows_without_view_are_readable(tmp_path):
    import json as _json

    path = tmp_path / "sessions" / "runs.jsonl"
    path.parent.mkdir(parents=True)
    path.write_text(
        _json.dumps(
            {
                "run_id": "old",
                "question": "q",
                "tool_calls": [],
                "citations": [],
                "note_path": None,
            }
        )
        + "\n"
    )
    store = SessionStore(store_path=path)
    row = store.recent_runs(1)[0]
    assert row["run_id"] == "old"
    assert row["view"]["rating"] is None


def test_recorded_views_skips_runs_without_a_rating(tmp_path):
    store = SessionStore(store_path=tmp_path / "sessions" / "runs.jsonl")
    store.start_run("run-a", "q1")
    store.finish_run()
    store.start_run("run-b", "q2")
    store.finish_run(view={"rating": "bearish", "tickers": ["TSLA"]})

    assert [r["run_id"] for r in store.recorded_views()] == ["run-b"]


def test_current_tool_calls_exposes_open_run(tmp_path):
    store = SessionStore(store_path=tmp_path / "sessions" / "runs.jsonl")
    assert store.current_tool_calls() == []
    store.start_run("run-c", "q")
    store.record_tool_call("get_quote", {"ticker": "NVDA"}, "ok")
    assert store.current_tool_calls()[0]["args"]["ticker"] == "NVDA"
