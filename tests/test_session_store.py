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
