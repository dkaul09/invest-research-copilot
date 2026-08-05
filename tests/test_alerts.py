"""Price-watch condition store: round-trip, validation, resilience."""

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
    assert created["alert"]["baseline"] == "prev_close"
    assert created["alert"]["enabled"] is True
    assert store.list_price_alerts()["alerts"][0]["id"] == created["alert"]["id"]


def test_saved_condition_says_delivery_is_not_wired_up(store):
    created = store.add_price_alert("NVDA", "down", 5.0)
    assert "not wired up yet" in created["note"]


def test_remove(store):
    created = store.add_price_alert("NVDA", "down", 5.0)
    assert store.remove_price_alert(created["alert"]["id"])["removed"] is True
    assert store.list_price_alerts()["alerts"] == []


def test_remove_unknown_id_reports_cleanly(store):
    assert store.remove_price_alert("nope")["removed"] is False


def test_rejects_bad_direction(store):
    with pytest.raises(ValueError):
        store.add_price_alert("NVDA", "sideways", 5.0)


def test_rejects_bad_baseline(store):
    with pytest.raises(ValueError):
        store.add_price_alert("NVDA", "down", 5.0, baseline="since_forever")


def test_rejects_non_positive_pct(store):
    with pytest.raises(ValueError):
        store.add_price_alert("NVDA", "down", 0)


def test_rejects_blank_ticker(store):
    with pytest.raises(ValueError):
        store.add_price_alert("   ", "down", 5.0)


def test_accepts_view_price_baseline(store):
    created = store.add_price_alert("NVDA", "down", 15.0, baseline="view_price")
    assert created["alert"]["baseline"] == "view_price"


def test_list_on_missing_file_is_empty(store):
    assert store.list_price_alerts()["alerts"] == []


def test_corrupt_file_reads_as_empty(store):
    store.ALERTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    store.ALERTS_PATH.write_text("{not json", encoding="utf-8")
    assert store.list_price_alerts()["alerts"] == []


def test_multiple_conditions_coexist(store):
    store.add_price_alert("NVDA", "down", 5.0)
    store.add_price_alert("TSLA", "up", 10.0, baseline="30d")
    assert {a["ticker"] for a in store.list_price_alerts()["alerts"]} == {"NVDA", "TSLA"}
