"""Append-only ledger of research runs.

Every research question the assistant works on is recorded as one JSON line
in ``data/sessions/runs.jsonl``: the question, which tools were called with
what arguments, the metric values produced (with their input provenance),
and the filing citations used. The ledger is append-only by design — no
record is ever edited or deleted in place — so a run is always auditable and
a follow-up question can be answered from prior provenance instead of
recomputing everything from scratch.

This is intentionally a flat file, not a database: for a personal, single-user
research tool, a JSONL file is simple, greppable, diffable, and requires no
extra service to run.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

DEFAULT_STORE_PATH = Path(__file__).resolve().parents[2] / "data" / "sessions" / "runs.jsonl"


class SessionStore:
    def __init__(self, store_path: Path = DEFAULT_STORE_PATH) -> None:
        self._path = store_path
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._current_run: dict[str, Any] | None = None

    def start_run(self, run_id: str, question: str) -> None:
        self._current_run = {
            "run_id": run_id,
            "question": question,
            "tool_calls": [],
            "citations": [],
            "note_path": None,
        }

    def record_tool_call(self, tool_name: str, args: dict[str, Any], result_summary: Any) -> None:
        if self._current_run is None:
            raise RuntimeError("record_tool_call called before start_run")
        self._current_run["tool_calls"].append(
            {"tool": tool_name, "args": args, "result_summary": result_summary}
        )

    def record_citation(self, ticker: str, section: str, source_url: str) -> None:
        if self._current_run is None:
            raise RuntimeError("record_citation called before start_run")
        self._current_run["citations"].append(
            {"ticker": ticker, "section": section, "source_url": source_url}
        )

    def finish_run(self, note_path: str | None = None) -> dict[str, Any]:
        if self._current_run is None:
            raise RuntimeError("finish_run called before start_run")
        self._current_run["note_path"] = note_path
        record = self._current_run
        with open(self._path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record) + "\n")
        self._current_run = None
        return record

    def recent_runs(self, n: int = 5) -> list[dict[str, Any]]:
        if not self._path.exists():
            return []
        with open(self._path, "r", encoding="utf-8") as f:
            lines = [json.loads(line) for line in f if line.strip()]
        return lines[-n:]

    def provenance_for(self, ticker: str) -> list[dict[str, Any]]:
        """All recorded tool calls and citations that touched ``ticker``."""
        ticker = ticker.upper()
        matches = []
        for run in self.recent_runs(n=10_000):
            touched = any(
                (call.get("args", {}).get("ticker") == ticker) for call in run["tool_calls"]
            ) or any(c["ticker"] == ticker for c in run["citations"])
            if touched:
                matches.append(run)
        return matches


_default_store: SessionStore | None = None


def get_default_store() -> SessionStore:
    global _default_store
    if _default_store is None:
        _default_store = SessionStore()
    return _default_store
