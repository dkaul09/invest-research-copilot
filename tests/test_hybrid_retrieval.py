"""Hybrid retrieval: fusion arithmetic, graceful degradation, and the
lexical-gap case that motivated adding embeddings at all.

The fusion tests are pure arithmetic and always run. The tests that need a
real embedding backend skip when none is available, so the suite still
passes on a machine that has not installed one — which is the same
degradation path production takes.
"""

from __future__ import annotations

import numpy as np
import pytest

from src.tools import embeddings
from src.tools.filings_search import FilingsIndex, search_filings
from src.tools.hybrid_search import dense_ranking, fuse, reciprocal_rank_fusion


def _backend_available() -> bool:
    return embeddings.get_backend() is not None


needs_embeddings = pytest.mark.skipif(
    not _backend_available(), reason="no embedding backend installed"
)


# --- fusion arithmetic (no backend needed) ---------------------------------


def test_rrf_rewards_agreement_between_rankers():
    """A doc both rankers like beats one only a single ranker found.

    Note this is about presence in both lists, not about averaging ranks:
    because 1/(k+x) is convex, ranks 1-and-3 actually edge out 2-and-2. The
    property that holds is that contributing twice beats contributing once.
    """
    fused = dict(reciprocal_rank_fusion([[1, 2, 3], [3, 2, 1]]))
    assert fused[2] > fused[1] / 2  # doc 2 scores from both rankers
    assert min(fused.values()) > 0

    # Agreed-on doc vs. a doc that tops one list and is missing from the other.
    agreed = dict(reciprocal_rank_fusion([[1, 2], [1, 2]]))
    single = dict(reciprocal_rank_fusion([[1, 2], [3]]))
    assert agreed[1] > single[1]


def test_rrf_includes_documents_only_one_ranker_found():
    """The whole point: a doc absent from BM25 must still be reachable."""
    fused = dict(reciprocal_rank_fusion([[1, 2], [99]]))
    assert 99 in fused


def test_rrf_ties_resolve_deterministically_by_index():
    # Symmetric inputs give doc 1 and doc 2 identical scores; the lower
    # index must win every time rather than depending on dict iteration.
    for _ in range(5):
        fused = reciprocal_rank_fusion([[1, 2], [2, 1]])
        assert [doc for doc, _ in fused] == [1, 2]


def test_rrf_scores_match_the_formula():
    fused = dict(reciprocal_rank_fusion([[7]], k=60))
    assert fused[7] == pytest.approx(1 / 61)


def test_dense_ranking_sorts_by_cosine_similarity():
    docs = np.array([[1.0, 0.0], [0.7071, 0.7071], [0.0, 1.0]], dtype=np.float32)
    query = np.array([1.0, 0.0], dtype=np.float32)
    assert dense_ranking(query, docs, depth=3) == [0, 1, 2]


def test_dense_ranking_handles_empty_corpus():
    assert dense_ranking(np.array([1.0, 0.0]), np.empty((0, 2))) == []


def test_fuse_reports_per_ranker_provenance():
    results = fuse(bm25_ranking=[5], dense_rank=[9], top_k=2)
    provenance = {doc: prov for doc, _, prov in results}
    assert provenance[5]["bm25_rank"] == 1
    assert provenance[5]["dense_rank"] is None
    assert provenance[9]["dense_rank"] == 1
    assert provenance[9]["bm25_rank"] is None


# --- degradation -----------------------------------------------------------


def test_search_falls_back_to_pure_bm25_without_a_backend(monkeypatch):
    """No backend must mean working lexical search, not an exception."""
    monkeypatch.setattr(embeddings, "get_backend", lambda: None)
    monkeypatch.setattr("src.tools.filings_search.embed", lambda texts: None)

    index = FilingsIndex()
    results = index.search("gross margin", top_k=3)

    assert results
    assert all(r["retrieval"]["dense_rank"] is None for r in results)
    # Ranking must be exactly BM25's when the dense half is absent.
    scores = [r["bm25_score"] for r in results]
    assert scores == sorted(scores, reverse=True)


def test_results_always_carry_their_citation_tuple():
    """Hybrid ranking must not drop the fields a citation is built from."""
    for hit in search_filings("margin", top_k=3):
        assert hit["ticker"]
        assert hit["section"]
        assert hit["source_url"]


# --- the case that motivated embeddings ------------------------------------


@needs_embeddings
def test_closes_the_lexical_gap_bm25_could_not():
    """AAPL's supply-chain section never writes 'supply', 'chain', or
    'concentration' in its body — BM25 scored it 0.0 and ranked a margin
    discussion first. Hybrid must surface it."""
    index = FilingsIndex()
    target = "Risk Factors: Supply Chain Concentration"

    # Confirm the premise still holds: BM25 alone cannot find this chunk.
    chunk = next(c for c in index.chunks if c.section == target)
    body_only_tokens = set(chunk.text.lower().split())
    assert not {"supply", "chain", "concentration"} & body_only_tokens

    top = index.search("supply chain concentration risk", top_k=1)[0]
    assert top["section"] == target
    assert top["ticker"] == "AAPL"


@needs_embeddings
def test_retrieval_is_deterministic_across_repeated_queries():
    index = FilingsIndex()
    query = "competitive pressure in cloud services"
    first = [h["section"] for h in index.search(query, top_k=5)]
    for _ in range(3):
        assert [h["section"] for h in index.search(query, top_k=5)] == first


@needs_embeddings
def test_ticker_filter_still_constrains_dense_hits():
    """A dense hit from another issuer must not leak past the ticker filter."""
    for hit in search_filings("risk", ticker="NKE", top_k=5):
        assert hit["ticker"] == "NKE"


@needs_embeddings
def test_backend_is_reported_on_every_hit():
    hit = search_filings("margin", top_k=1)[0]
    assert hit["retrieval"]["backend"] != "none"


# --- embedding layer ------------------------------------------------------


@needs_embeddings
def test_embeddings_are_l2_normalized():
    vectors = embeddings.embed(["gross margin expanded", "supplier concentration"])
    norms = np.linalg.norm(vectors, axis=1)
    assert np.allclose(norms, 1.0, atol=1e-5)


@needs_embeddings
def test_cache_returns_identical_vectors_on_repeat():
    text = ["contract manufacturers concentrated in Asia"]
    assert np.array_equal(embeddings.embed(text), embeddings.embed(text))


@needs_embeddings
def test_semantic_neighbours_beat_unrelated_text():
    vectors = embeddings.embed(
        [
            "we depend on a small number of suppliers",
            "supply chain concentration",
            "the effective tax rate decreased",
        ]
    )
    related = float(vectors[0] @ vectors[1])
    unrelated = float(vectors[0] @ vectors[2])
    assert related > unrelated


def test_embeddings_disabled_by_environment(monkeypatch):
    """IRC_EMBEDDINGS=off must be an honest, total switch."""
    monkeypatch.setenv("IRC_EMBEDDINGS", "off")
    embeddings.reset_backend_for_tests()
    try:
        assert embeddings.get_backend() is None
        assert embeddings.backend_id() == "none"
        assert embeddings.embed(["anything"]) is None
    finally:
        monkeypatch.delenv("IRC_EMBEDDINGS", raising=False)
        embeddings.reset_backend_for_tests()
