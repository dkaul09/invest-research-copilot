"""Multi-conversation chat state: create/list/get/append/delete, and the
lazy TTL pruning that gives "auto-delete after a week of inactivity"."""

from datetime import datetime, timedelta, timezone

from src.state import conversations


def test_create_conversation_has_no_title_until_first_turn(tmp_path):
    conv = conversations.create_conversation(directory=tmp_path)
    assert conv["title"] is None
    assert conv["messages"] == []


def test_append_turn_sets_title_from_first_question(tmp_path):
    conv = conversations.create_conversation(directory=tmp_path)
    updated = conversations.append_turn(
        conv["id"], "What do you think of AAPL?", "Research note...", ["compute_metrics"], directory=tmp_path
    )
    assert updated["title"] == "What do you think of AAPL?"
    assert len(updated["messages"]) == 2
    assert updated["messages"][0] == {"role": "user", "text": "What do you think of AAPL?"}


def test_append_turn_does_not_overwrite_existing_title(tmp_path):
    conv = conversations.create_conversation(directory=tmp_path)
    conversations.append_turn(conv["id"], "First question", "answer 1", [], directory=tmp_path)
    updated = conversations.append_turn(conv["id"], "Second question", "answer 2", [], directory=tmp_path)
    assert updated["title"] == "First question"
    assert len(updated["messages"]) == 4


def test_title_truncates_long_first_question(tmp_path):
    conv = conversations.create_conversation(directory=tmp_path)
    long_question = "x" * 200
    updated = conversations.append_turn(conv["id"], long_question, "answer", [], directory=tmp_path)
    assert len(updated["title"]) <= conversations.TITLE_MAX_LEN
    assert updated["title"].endswith("…")


def test_get_conversation_returns_none_for_unknown_id(tmp_path):
    assert conversations.get_conversation("does-not-exist", directory=tmp_path) is None


def test_list_conversations_sorted_newest_first(tmp_path):
    a = conversations.create_conversation(directory=tmp_path)
    b = conversations.create_conversation(directory=tmp_path)
    conversations.append_turn(a["id"], "q", "a", [], directory=tmp_path)
    listing = conversations.list_conversations(directory=tmp_path)
    ids_by_recency = [c["id"] for c in listing]
    assert ids_by_recency[0] == a["id"]  # a was touched most recently
    assert b["id"] in ids_by_recency


def test_delete_conversation_removes_it(tmp_path):
    conv = conversations.create_conversation(directory=tmp_path)
    conversations.delete_conversation(conv["id"], directory=tmp_path)
    assert conversations.get_conversation(conv["id"], directory=tmp_path) is None


def test_list_conversations_prunes_stale_entries(tmp_path):
    conv = conversations.create_conversation(directory=tmp_path)
    # Force updated_at into the past, simulating a week-old chat.
    stale = conversations.get_conversation(conv["id"], directory=tmp_path)
    stale["updated_at"] = (datetime.now(timezone.utc) - timedelta(days=10)).isoformat()
    conversations._save(stale, tmp_path)

    listing = conversations.list_conversations(directory=tmp_path, ttl_days=7)
    assert listing == []
    assert conversations.get_conversation(conv["id"], directory=tmp_path) is None  # actually deleted


def test_list_conversations_keeps_recent_entries(tmp_path):
    conv = conversations.create_conversation(directory=tmp_path)
    listing = conversations.list_conversations(directory=tmp_path, ttl_days=7)
    assert len(listing) == 1
    assert listing[0]["id"] == conv["id"]


def test_append_turn_unknown_conversation_raises(tmp_path):
    import pytest

    with pytest.raises(ValueError):
        conversations.append_turn("does-not-exist", "q", "a", [], directory=tmp_path)
