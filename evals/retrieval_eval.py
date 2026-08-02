"""Recall@k and MRR for the BM25 filing search, independent of synthesis.

Scores retrieval on its own so a bad research note can be diagnosed as
"retrieval didn't find the right passage" vs. "synthesis ignored a passage
that was retrieved" — conflating the two makes failures hard to fix.
"""

from __future__ import annotations

from typing import Any

from src.tools.filings_search import search_filings


def _hit_matches(hit: dict[str, Any], relevant: tuple[str, str]) -> bool:
    return hit["ticker"] == relevant[0] and hit["section"] == relevant[1]


def score_query(query: str, relevant_chunks: list[list[str]], top_k: int = 5) -> dict[str, Any]:
    """relevant_chunks: list of [ticker, section] pairs considered relevant."""
    if not relevant_chunks:
        return {"recall_at_k": None, "mrr": None, "reason": "no labeled relevant chunks for this query"}

    relevant = [tuple(pair) for pair in relevant_chunks]
    results = search_filings(query, top_k=top_k)

    found = set()
    reciprocal_rank = 0.0
    for rank, hit in enumerate(results, start=1):
        for rel in relevant:
            if _hit_matches(hit, rel) and rel not in found:
                found.add(rel)
                if reciprocal_rank == 0.0:
                    reciprocal_rank = 1 / rank

    recall = len(found) / len(relevant)
    return {
        "recall_at_k": round(recall, 3),
        "mrr": round(reciprocal_rank, 3),
        "found": list(found),
        "missed": [r for r in relevant if r not in found],
    }


def run_retrieval_eval(golden_set: list[dict[str, Any]], top_k: int = 5) -> dict[str, Any]:
    per_query = []
    for item in golden_set:
        relevant = item.get("relevant_chunks", [])
        if not relevant:
            continue
        result = score_query(item["query_for_retrieval"], relevant, top_k=top_k)
        per_query.append({"id": item["id"], **result})

    if not per_query:
        return {"mean_recall_at_k": None, "mean_mrr": None, "per_query": []}

    mean_recall = sum(q["recall_at_k"] for q in per_query) / len(per_query)
    mean_mrr = sum(q["mrr"] for q in per_query) / len(per_query)
    return {"mean_recall_at_k": round(mean_recall, 3), "mean_mrr": round(mean_mrr, 3), "per_query": per_query}
