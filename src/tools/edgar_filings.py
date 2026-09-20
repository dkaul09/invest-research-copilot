"""Fetch and search the actual text of a company's latest 10-K from EDGAR.

Unlike the local filing corpus (hand-picked excerpts with clean ``## Heading``
sections), a real 10-K is one large HTML document with no consistent
heading structure across filers. This module strips HTML tags to plain
text, splits into fixed-size paragraph windows, and BM25-ranks those
windows for a query — the same deterministic ranking algorithm as
``filings_search.py``, just without section-name citations. Every result
still carries the real filing's source URL, so a citation always points at
an actual, verifiable document.
"""

from __future__ import annotations

import html
import math
import re
from dataclasses import dataclass
from typing import Any

from src.tools.edgar_client import EdgarLookupError, fetch_text, get_cik_for_ticker, get_latest_10k_filing
from src.tools.embeddings import backend_id, embed
from src.tools.hybrid_search import CANDIDATE_DEPTH, dense_ranking, fuse

_TAG_RE = re.compile(r"<[^>]+>")
_WHITESPACE_RE = re.compile(r"\s+")
_TOKEN_RE = re.compile(r"[a-z0-9]+")

_WINDOW_WORDS = 200
_STRIDE_WORDS = 150  # overlap between windows so a fact near a boundary isn't split out of every chunk


def _html_to_text(html_source: str) -> str:
    # Drop script/style blocks first so their content doesn't leak into text.
    html_source = re.sub(r"(?is)<(script|style).*?</\1>", " ", html_source)
    text = _TAG_RE.sub(" ", html_source)
    # Decode the full entity set, not just a hand-picked few: filings are
    # dense with &#8217; and &#8220;, and leaving them raw puts literal
    # entity codes inside quoted citations.
    text = html.unescape(text)
    return _WHITESPACE_RE.sub(" ", text).strip()


def _windowed_chunks(text: str) -> list[str]:
    words = text.split(" ")
    chunks = []
    i = 0
    while i < len(words):
        window = words[i : i + _WINDOW_WORDS]
        if len(window) < 30:  # drop a tiny trailing fragment
            break
        chunks.append(" ".join(window))
        i += _STRIDE_WORDS
    return chunks


@dataclass
class LiveChunk:
    ticker: str
    company: str
    source_url: str
    filing_date: str
    text: str
    tokens: list[str]


def _tokenize(text: str) -> list[str]:
    return _TOKEN_RE.findall(text.lower())


def fetch_live_filing_chunks(ticker: str, force_refresh: bool = False) -> tuple[list[LiveChunk], dict[str, Any]]:
    """Fetch the latest 10-K for ticker and return its chunks + filing metadata.

    Raises EdgarLookupError if the ticker or its latest 10-K can't be found.
    """
    cik = get_cik_for_ticker(ticker)
    if cik is None:
        raise EdgarLookupError(f"Could not resolve ticker '{ticker}' to a CIK via SEC EDGAR.")

    filing = get_latest_10k_filing(cik)
    if filing is None:
        raise EdgarLookupError(f"No 10-K found in SEC EDGAR submissions for '{ticker}'.")

    html = fetch_text(filing["url"], cache_key=f"filing_{cik}_{filing['accession_number']}", force_refresh=force_refresh)
    text = _html_to_text(html)
    windows = _windowed_chunks(text)

    chunks = [
        LiveChunk(
            ticker=ticker.upper(),
            company=ticker.upper(),
            source_url=filing["url"],
            filing_date=filing["filing_date"],
            text=w,
            tokens=_tokenize(w),
        )
        for w in windows
    ]
    return chunks, filing


class _BM25:
    """Hybrid BM25 + dense retrieval over live-fetched filing windows.

    Named for its lexical half for continuity, but it fuses two rankings.
    This path matters more than the local corpus: blind 200-word windows
    have no section headings to lean on, and this is what answers every
    ticker outside AAPL/MSFT/NKE.
    """

    K1 = 1.5
    B = 0.75

    def __init__(self, chunks: list[LiveChunk]) -> None:
        self.chunks = chunks
        self._doc_vectors = None
        self._doc_lengths = [len(c.tokens) for c in chunks]
        self._avg_doc_length = sum(self._doc_lengths) / len(self._doc_lengths) if self._doc_lengths else 0.0
        self._df: dict[str, int] = {}
        for c in chunks:
            for term in set(c.tokens):
                self._df[term] = self._df.get(term, 0) + 1
        self._n_docs = len(chunks)

    def _idf(self, term: str) -> float:
        df = self._df.get(term, 0)
        return max(0.0, math.log((self._n_docs - df + 0.5) / (df + 0.5) + 1))

    def _vectors(self):
        if self._doc_vectors is None:
            self._doc_vectors = embed([c.text for c in self.chunks])
        return self._doc_vectors

    def search(self, query: str, top_k: int) -> list[dict[str, Any]]:
        query_tokens = _tokenize(query)
        if not query_tokens:
            return []

        lexical = []
        for i, chunk in enumerate(self.chunks):
            term_counts: dict[str, int] = {}
            for t in chunk.tokens:
                term_counts[t] = term_counts.get(t, 0) + 1
            score = 0.0
            doc_length = len(chunk.tokens)
            for term in query_tokens:
                tf = term_counts.get(term, 0)
                if tf == 0:
                    continue
                idf = self._idf(term)
                denom = tf + self.K1 * (1 - self.B + self.B * doc_length / (self._avg_doc_length or 1))
                score += idf * (tf * (self.K1 + 1)) / denom
            if score > 0:
                lexical.append((score, i))

        lexical.sort(key=lambda pair: (-pair[0], pair[1]))
        bm25_ranking = [i for _, i in lexical]
        bm25_scores = {i: s for s, i in lexical}

        doc_vectors = self._vectors()
        if doc_vectors is None:
            chosen = [(i, bm25_scores[i], {"bm25_rank": r, "dense_rank": None})
                      for r, i in enumerate(bm25_ranking[:top_k], start=1)]
        else:
            query_vector = embed([query])
            dense_rank = dense_ranking(query_vector[0], doc_vectors, depth=CANDIDATE_DEPTH)
            chosen = fuse(bm25_ranking[:CANDIDATE_DEPTH], dense_rank, top_k)

        results = []
        for doc_index, score, provenance in chosen:
            chunk = self.chunks[doc_index]
            results.append(
                {
                    "score": round(float(score), 4),
                    "bm25_score": round(bm25_scores.get(doc_index, 0.0), 4),
                    "retrieval": {**provenance, "backend": backend_id()},
                    "ticker": chunk.ticker,
                    "source_url": chunk.source_url,
                    "filing_date": chunk.filing_date,
                    "text": chunk.text,
                }
            )
        return results


def search_live_filing(ticker: str, query: str, top_k: int = 3) -> dict[str, Any]:
    """Fetch (or reuse cached) the ticker's latest 10-K and BM25-search it.

    Returns {"filing": {...}, "results": [...]}. Raises EdgarLookupError if
    the ticker can't be resolved.
    """
    chunks, filing = fetch_live_filing_chunks(ticker)
    index = _BM25(chunks)
    results = index.search(query, top_k=top_k)
    return {"filing": filing, "results": results}
