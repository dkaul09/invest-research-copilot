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
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DEFAULT_STORE_PATH = Path(__file__).resolve().parents[2] / "data" / "sessions" / "runs.jsonl"

EMPTY_VIEW: dict[str, Any] = {
    "rating": None,
    "tickers": [],
    "view_price": {},
    "change_my_mind": [],
}


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

    def finish_run(
        self,
        note_path: str | None = None,
        note_text: str | None = None,
        view: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Close the open run and append it to the ledger.

        ``note_text`` is the note itself: passing it persists the markdown
        under ``data/notes/<run_id>.md`` and sets ``note_path`` to point at
        it. ``note_path`` remains accepted for callers that manage their own
        note files. ``view`` records what the note actually concluded — the
        rating, the tickers it covered, and the price each was quoted at —
        so a stated view can later be checked against what happened.
        """
        if self._current_run is None:
            raise RuntimeError("finish_run called before start_run")

        record = self._current_run
        record["note_path"] = note_path
        record["timestamp"] = (
            datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
        )
        record["view"] = {**EMPTY_VIEW, **(view or {})}

        if note_text:
            notes_dir = self._path.parent.parent / "notes"
            notes_dir.mkdir(parents=True, exist_ok=True)
            note_file = notes_dir / f"{record['run_id']}.md"
            note_file.write_text(note_text, encoding="utf-8")
            # Stored relative to the ledger so the pair stays portable if the
            # data directory moves. ``notes/`` is a sibling of ``sessions/``,
            # so this is a "../notes/<run_id>.md" style path.
            record["note_path"] = os.path.relpath(note_file, self._path.parent)

        with open(self._path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record) + "\n")
        self._current_run = None
        return record

    def recent_runs(self, n: int = 5) -> list[dict[str, Any]]:
        if not self._path.exists():
            return []
        with open(self._path, "r", encoding="utf-8") as f:
            lines = [json.loads(line) for line in f if line.strip()]
        # Rows written before views were recorded lack the key entirely.
        # Normalising on read keeps every consumer free of defensive lookups.
        for row in lines:
            row.setdefault("view", dict(EMPTY_VIEW))
            row.setdefault("timestamp", None)
        return lines[-n:]

    def recorded_views(self) -> list[dict[str, Any]]:
        """Every run that stated a rating and has a timestamp, oldest first."""
        return [
            r
            for r in self.recent_runs(n=10_000)
            if (r.get("view") or {}).get("rating") and r.get("timestamp")
        ]

    def current_tool_calls(self) -> list[dict[str, Any]]:
        """Tool calls recorded so far in the currently open run."""
        if self._current_run is None:
            return []
        return list(self._current_run["tool_calls"])

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
