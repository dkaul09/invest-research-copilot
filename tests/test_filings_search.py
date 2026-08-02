"""Filing retrieval: every hit carries a citation, no fabrication on empty query."""

from src.tools.filings_search import FilingsIndex, get_default_index


def test_every_hit_carries_source_and_section():
    index = get_default_index()
    results = index.search("China market", top_k=3)
    assert results, "expected at least one result for a query present in the corpus"
    for hit in results:
        assert hit["ticker"]
        assert hit["section"]
        assert hit["source_url"]


def test_relevant_query_ranks_the_right_document_first():
    index = get_default_index()
    results = index.search("supplier concentration manufacturing China", ticker="AAPL", top_k=1)
    assert results
    assert results[0]["ticker"] == "AAPL"
    assert "Supply Chain" in results[0]["section"]


def test_empty_query_returns_no_fabricated_results():
    index = get_default_index()
    results = index.search("", top_k=3)
    assert results == []


def test_scoped_ticker_only_returns_that_tickers_chunks():
    index = get_default_index()
    results = index.search("margin", ticker="NKE", top_k=5)
    assert results
    assert all(hit["ticker"] == "NKE" for hit in results)


def test_index_loads_all_three_seed_filings():
    index = FilingsIndex()
    tickers = {c.ticker for c in index.chunks}
    assert tickers == {"AAPL", "MSFT", "NKE"}
