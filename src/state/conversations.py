"""Multi-conversation chat state for the web/Telegram frontends.

Distinct from ``session_store.py``: that module is an audit ledger of
research provenance (which tool calls backed which claims), append-only
and never read back into a prompt. This module is what actually lets a
"chat" have memory across turns — the message history persisted here is
replayed back into the Anthropic API on the next question in the same
conversation. Without it, every question was a fresh, memoryless request
(the original design), which is fine for a single research question but
not for "New chat" / "continue this chat" style behavior.

One JSON file per conversation under ``data/conversations/`` (gitignored —
this is personal chat history, not a fixture to ship). Only the
user-visible turns (question text, final answer text) are persisted, not
raw tool-use blocks — simpler, smaller, and robust across code changes to
the tool schemas. A conversation still has continuity turn-to-turn because
the assistant's own prior answers (which summarize findings and citations)
are replayed as context.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

DEFAULT_CONVERSATIONS_DIR = Path(__file__).resolve().parents[2] / "data" / "conversations"
DEFAULT_TTL_DAYS = 7
TITLE_MAX_LEN = 60


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _path_for(conversation_id: str, directory: Path) -> Path:
    return directory / f"{conversation_id}.json"


def _derive_title(first_question: str) -> str:
    title = first_question.strip().replace("\n", " ")
    if len(title) > TITLE_MAX_LEN:
        title = title[: TITLE_MAX_LEN - 1].rstrip() + "…"
    return title or "New chat"


def create_conversation(directory: Path = DEFAULT_CONVERSATIONS_DIR) -> dict[str, Any]:
    directory.mkdir(parents=True, exist_ok=True)
    conversation_id = str(uuid.uuid4())
    now = _now_iso()
    conversation = {
        "id": conversation_id,
        "title": None,
        "created_at": now,
        "updated_at": now,
        "messages": [],
    }
    _save(conversation, directory)
    return conversation


def _save(conversation: dict[str, Any], directory: Path) -> None:
    with open(_path_for(conversation["id"], directory), "w", encoding="utf-8") as f:
        json.dump(conversation, f, indent=2)


def get_conversation(conversation_id: str, directory: Path = DEFAULT_CONVERSATIONS_DIR) -> dict[str, Any] | None:
    path = _path_for(conversation_id, directory)
    if not path.exists():
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def append_turn(
    conversation_id: str,
    question: str,
    answer: str,
    tool_calls: list[str],
    directory: Path = DEFAULT_CONVERSATIONS_DIR,
) -> dict[str, Any]:
    """Append one question/answer turn and return the updated conversation."""
    conversation = get_conversation(conversation_id, directory=directory)
    if conversation is None:
        raise ValueError(f"No conversation with id {conversation_id}")

    if conversation["title"] is None:
        conversation["title"] = _derive_title(question)

    conversation["messages"].append({"role": "user", "text": question})
    conversation["messages"].append({"role": "assistant", "text": answer, "tool_calls": tool_calls})
    conversation["updated_at"] = _now_iso()
    _save(conversation, directory)
    return conversation


def delete_conversation(conversation_id: str, directory: Path = DEFAULT_CONVERSATIONS_DIR) -> None:
    path = _path_for(conversation_id, directory)
    if path.exists():
        path.unlink()


def list_conversations(
    directory: Path = DEFAULT_CONVERSATIONS_DIR,
    ttl_days: int = DEFAULT_TTL_DAYS,
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    """List conversations newest-first, pruning (deleting) any past the TTL.

    Pruning happens lazily here rather than via a background job — simple
    and sufficient for a single-user local tool; the list is what a
    sidebar calls on every load anyway, so staleness never exceeds one
    page load.
    """
    if not directory.exists():
        return []

    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(days=ttl_days)

    summaries = []
    for path in directory.glob("*.json"):
        with open(path, "r", encoding="utf-8") as f:
            conversation = json.load(f)
        updated_at = datetime.fromisoformat(conversation["updated_at"])
        if updated_at < cutoff:
            path.unlink()
            continue
        summaries.append(
            {
                "id": conversation["id"],
                "title": conversation["title"] or "New chat",
                "created_at": conversation["created_at"],
                "updated_at": conversation["updated_at"],
                "message_count": len(conversation["messages"]),
            }
        )

    summaries.sort(key=lambda c: c["updated_at"], reverse=True)
    return summaries
