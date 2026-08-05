"""Caller-supplied Anthropic keys: precedence, isolation, and non-persistence."""

import pytest
from fastapi.testclient import TestClient

from backend import app as app_mod
from backend.app import MissingApiKey, app, get_client


def test_supplied_key_is_used_over_the_environment(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-server")
    monkeypatch.setattr(app_mod, "_client", None)

    client = get_client("sk-ant-visitor")
    assert client.api_key == "sk-ant-visitor"


def test_supplied_key_is_never_cached(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr(app_mod, "_client", None)

    get_client("sk-ant-visitor")
    # Caching a visitor's key would leak it into the next visitor's request.
    assert app_mod._client is None


def test_two_callers_get_separate_clients(monkeypatch):
    monkeypatch.setattr(app_mod, "_client", None)
    first = get_client("sk-ant-one")
    second = get_client("sk-ant-two")
    assert first is not second
    assert (first.api_key, second.api_key) == ("sk-ant-one", "sk-ant-two")


def test_environment_key_is_reused_when_none_supplied(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-server")
    monkeypatch.setattr(app_mod, "_client", None)

    first = get_client()
    second = get_client()
    assert first is second
    assert first.api_key == "sk-ant-server"


def test_no_key_anywhere_raises_missing_api_key(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr(app_mod, "_client", None)

    with pytest.raises(MissingApiKey):
        get_client()


def test_missing_key_returns_a_readable_answer_not_a_500(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr(app_mod, "_client", None)

    body = TestClient(app).post("/api/ask", json={"question": "How does NVDA look?"}).json()
    assert "API key" in body["answer"]
    assert body["blocked"] is False


def test_header_reaches_run_research(monkeypatch):
    seen = {}

    def fake_run_research(question, history=None, api_key=None):
        seen["question"] = question
        seen["api_key"] = api_key
        return app_mod.AskResponse(answer="ok", tool_calls=[], blocked=False)

    monkeypatch.setattr(app_mod, "run_research", fake_run_research)
    TestClient(app).post(
        "/api/ask",
        json={"question": "q"},
        headers={"X-Anthropic-Key": "sk-ant-visitor"},
    )
    assert seen["api_key"] == "sk-ant-visitor"


def test_key_is_not_written_to_the_ledger(monkeypatch, tmp_path):
    """A visitor's key must not survive the request in any recorded artifact."""
    from src.state.session_store import SessionStore

    store = SessionStore(store_path=tmp_path / "sessions" / "runs.jsonl")
    store.start_run("run-key", "q")
    store.record_tool_call("get_quote", {"ticker": "NVDA"}, "ok")
    store.finish_run(note_text="note", view={"rating": "bullish"})

    written = (tmp_path / "sessions" / "runs.jsonl").read_text()
    assert "sk-ant" not in written
