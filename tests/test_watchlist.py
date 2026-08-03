"""Personal watchlist: the one intentionally-mutable piece of state.

Unlike account/trade data, adding or removing a ticker from a watchlist
isn't a trade, so these tests confirm the opposite property from the
safety tests elsewhere: this specific, narrow surface IS writable, and
behaves correctly (idempotent add, clean remove, seeded default).
"""

from pathlib import Path

from src.tools.watchlist import add_to_watchlist, get_watchlist, remove_from_watchlist


def test_seeds_default_watchlist_on_first_read(tmp_path):
    path = tmp_path / "watchlist.json"
    assert not path.exists()
    items = get_watchlist(path=path)
    assert path.exists()
    tickers = {i["ticker"] for i in items}
    assert "AMD" in tickers


def test_add_appends_new_ticker(tmp_path):
    path = tmp_path / "watchlist.json"
    get_watchlist(path=path)  # seed
    items = add_to_watchlist("NVDA", sector="Technology", path=path)
    tickers = [i["ticker"] for i in items]
    assert "NVDA" in tickers


def test_add_is_idempotent(tmp_path):
    path = tmp_path / "watchlist.json"
    add_to_watchlist("NVDA", path=path)
    items = add_to_watchlist("NVDA", path=path)
    assert [i["ticker"] for i in items].count("NVDA") == 1


def test_add_uppercases_ticker(tmp_path):
    path = tmp_path / "watchlist.json"
    items = add_to_watchlist("nvda", path=path)
    assert "NVDA" in [i["ticker"] for i in items]
    assert "nvda" not in [i["ticker"] for i in items]


def test_remove_deletes_ticker(tmp_path):
    path = tmp_path / "watchlist.json"
    add_to_watchlist("NVDA", path=path)
    items = remove_from_watchlist("NVDA", path=path)
    assert "NVDA" not in [i["ticker"] for i in items]


def test_remove_nonexistent_ticker_is_a_noop(tmp_path):
    path = tmp_path / "watchlist.json"
    get_watchlist(path=path)  # seed
    before = len(get_watchlist(path=path))
    items = remove_from_watchlist("ZZZZ", path=path)
    assert len(items) == before
