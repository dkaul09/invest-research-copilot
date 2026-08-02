"""Retrieval over a local corpus of SEC filing excerpts.

Each file in ``data/filings/`` is a Markdown document with YAML front matter
(ticker, company, form, fiscal_year, source_url, fundamentals) followed by
``## Heading`` sections. We chunk by section and rank chunks with a small,
dependency-free BM25 implementation (Okapi BM25). Every result carries the
source document, section heading, and source URL — a citation is not
optional metadata here, it's the whole point: an assistant claim without one
of these tuples attached is not allowed to appear in a research note.

Nothing here calls an LLM or a network API. Ranking is deterministic and
therefore testable: the same query against the same corpus always returns
the same ordering.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

DEFAULT_FILINGS_DIR = Path(__file__).resolve().parents[2] / "data" / "filings"

_TOKEN_RE = re.compile(r"[a-z0-9]+")


def _tokenize(text: str) -> list[str]:
    return _TOKEN_RE.findall(text.lower())


@dataclass
class Chunk:
    ticker: str
    company: str
    form: str
    fiscal_year: int
    source_url: str
    section: str
    text: str
    tokens: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.tokens:
            self.tokens = _tokenize(self.text)


def _parse_document(path: Path) -> list[Chunk]:
    raw = path.read_text(encoding="utf-8")
    if not raw.startswith("---"):
        raise ValueError(f"{path} is missing YAML front matter")

    _, front_matter_raw, body = raw.split("---", 2)
    meta = yaml.safe_load(front_matter_raw)

    chunks: list[Chunk] = []
    # Split the body into sections on '## Heading' lines.
    sections = re.split(r"(?m)^## (.+)$", body)
    # sections[0] is any leading text before the first heading (ignored);
    # then alternating (heading, content) pairs.
    for i in range(1, len(sections), 2):
        heading = sections[i].strip()
        content = sections[i + 1].strip()
        if not content:
            continue
        chunks.append(
            Chunk(
                ticker=meta["ticker"],
                company=meta.get("company", meta["ticker"]),
                form=meta.get("form", "10-K"),
                fiscal_year=meta.get("fiscal_year"),
                source_url=meta.get("source_url", ""),
                section=heading,
                text=content,
            )
        )
    return chunks


class FilingsIndex:
    """BM25 index over chunked filing excerpts."""

    K1 = 1.5
    B = 0.75

    def __init__(self, filings_dir: Path = DEFAULT_FILINGS_DIR) -> None:
        self.chunks: list[Chunk] = []
        for path in sorted(filings_dir.glob("*.md")):
            self.chunks.extend(_parse_document(path))

        self._doc_lengths = [len(c.tokens) for c in self.chunks]
        self._avg_doc_length = (
            sum(self._doc_lengths) / len(self._doc_lengths) if self._doc_lengths else 0.0
        )
        self._df: dict[str, int] = {}
        for c in self.chunks:
            for term in set(c.tokens):
                self._df[term] = self._df.get(term, 0) + 1
        self._n_docs = len(self.chunks)

    def _idf(self, term: str) -> float:
        df = self._df.get(term, 0)
        # Standard BM25 idf with a floor of 0 to avoid negative weights on
        # terms that appear in the majority of documents.
        return max(0.0, math.log((self._n_docs - df + 0.5) / (df + 0.5) + 1))

    def _score(self, query_tokens: list[str], chunk: Chunk, doc_length: int) -> float:
        score = 0.0
        term_counts: dict[str, int] = {}
        for t in chunk.tokens:
            term_counts[t] = term_counts.get(t, 0) + 1
        for term in query_tokens:
            tf = term_counts.get(term, 0)
            if tf == 0:
                continue
            idf = self._idf(term)
            denom = tf + self.K1 * (1 - self.B + self.B * doc_length / (self._avg_doc_length or 1))
            score += idf * (tf * (self.K1 + 1)) / denom
        return score

    def search(
        self,
        query: str,
        top_k: int = 3,
        ticker: str | None = None,
    ) -> list[dict[str, Any]]:
        query_tokens = _tokenize(query)
        if not query_tokens:
            return []

        candidates = self.chunks
        if ticker:
            candidates = [c for c in candidates if c.ticker == ticker.upper()]

        scored = []
        for chunk in candidates:
            score = self._score(query_tokens, chunk, len(chunk.tokens))
            if score > 0:
                scored.append((score, chunk))

        scored.sort(key=lambda pair: pair[0], reverse=True)

        return [
            {
                "score": round(score, 4),
                "ticker": chunk.ticker,
                "company": chunk.company,
                "form": chunk.form,
                "fiscal_year": chunk.fiscal_year,
                "section": chunk.section,
                "text": chunk.text,
                "source_url": chunk.source_url,
            }
            for score, chunk in scored[:top_k]
        ]


_default_index: FilingsIndex | None = None


def get_default_index() -> FilingsIndex:
    global _default_index
    if _default_index is None:
        _default_index = FilingsIndex()
    return _default_index


def search_filings(query: str, top_k: int = 3, ticker: str | None = None) -> list[dict[str, Any]]:
    """Public entry point used by the MCP tool and the skill workflow."""
    return get_default_index().search(query, top_k=top_k, ticker=ticker)
