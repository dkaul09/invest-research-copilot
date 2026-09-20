"""Reciprocal Rank Fusion over a BM25 ranking and a dense ranking.

Why fuse ranks rather than blend scores: a BM25 score and a cosine
similarity live on different, unbounded, corpus-dependent scales. Any
weighted sum of the two needs a normalization constant that has to be
retuned whenever the corpus changes — and this project searches three
corpora of wildly different shapes (15 curated sections, a few hundred
10-K windows, a multi-megabyte trust prospectus). RRF discards the scores
and keeps only each ranker's sequence, so there is nothing to retune:

    score(d) = sum over rankers of 1 / (K + rank(d))

K=60 is the constant from the original RRF paper and the usual default. It
damps the difference between ranks 1 and 2 enough that one ranker cannot
dominate on its own, while still rewarding agreement between the two.

The union is the point. BM25 alone scored the correct chunk 0.0 for
"supply chain concentration risk" because the body says "suppliers" and
"contract manufacturers" instead — it was absent from the BM25 ranking at
any depth. Fusion must therefore consider documents that only one ranker
retrieved, never merely rearrange BM25's hits.

Fusion is deterministic: the same query against the same corpus with the
same embedding backend produces the same ranking, which is what keeps
`evals/retrieval_eval.py` meaningful.
"""

from __future__ import annotations

from typing import Any, Sequence

import numpy as np

RRF_K = 60

# Retrieve deeper than the caller asked for before fusing. A chunk that
# BM25 ranks 12th and the dense ranker ranks 1st should be able to win; if
# both lists were truncated at top_k first, it could never enter the pool.
CANDIDATE_DEPTH = 25


def reciprocal_rank_fusion(
    rankings: Sequence[Sequence[int]],
    k: int = RRF_K,
) -> list[tuple[int, float]]:
    """Fuse ranked lists of document indices into one (index, score) list.

    Each input is a sequence of document indices, best first. Documents
    missing from a ranking simply contribute nothing for that ranker.
    """
    scores: dict[int, float] = {}
    for ranking in rankings:
        for rank, doc_index in enumerate(ranking, start=1):
            scores[doc_index] = scores.get(doc_index, 0.0) + 1.0 / (k + rank)

    # Sort by score descending, then by index ascending, so ties resolve
    # deterministically instead of by dict insertion sequence.
    return sorted(scores.items(), key=lambda pair: (-pair[1], pair[0]))


def dense_ranking(
    query_vector: np.ndarray,
    doc_vectors: np.ndarray,
    depth: int = CANDIDATE_DEPTH,
) -> list[int]:
    """Indices of the `depth` nearest doc vectors, best first.

    Both sides are already L2-normalized by the embedding layer, so a dot
    product is cosine similarity.
    """
    if doc_vectors is None or len(doc_vectors) == 0:
        return []
    similarities = doc_vectors @ query_vector.reshape(-1)
    depth = min(depth, len(similarities))
    # argpartition gets the top-`depth` set cheaply; only those get sorted.
    top = np.argpartition(-similarities, depth - 1)[:depth]
    return [int(i) for i in top[np.argsort(-similarities[top])]]


def fuse(
    bm25_ranking: Sequence[int],
    dense_rank: Sequence[int],
    top_k: int,
) -> list[tuple[int, float, dict[str, Any]]]:
    """Fuse two rankings and return the top_k with per-ranker provenance.

    The third element records where each result came from, so a caller can
    tell a lexical hit from one only the embeddings found — useful when
    debugging why a passage was retrieved.
    """
    bm25_positions = {doc: rank for rank, doc in enumerate(bm25_ranking, start=1)}
    dense_positions = {doc: rank for rank, doc in enumerate(dense_rank, start=1)}

    fused = reciprocal_rank_fusion([bm25_ranking, dense_rank])
    results = []
    for doc_index, score in fused[:top_k]:
        results.append(
            (
                doc_index,
                score,
                {
                    "bm25_rank": bm25_positions.get(doc_index),
                    "dense_rank": dense_positions.get(doc_index),
                },
            )
        )
    return results
