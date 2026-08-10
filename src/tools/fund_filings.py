"""Fetch and search a fund's actual SEC filings.

A fund's primary sources are not the ones the equity path reads. There is
no 10-K; what a registered fund files instead is:

- **497K** — the summary prospectus. Short, and the densest single source
  for objective, benchmark index, stated expense ratio, and principal
  risks. Searched first for exactly that reason.
- **485BPOS** — the full statutory prospectus: replication method,
  distribution policy, securities lending permissions, tax treatment.
- **N-CSR / N-CSRS** — annual and semi-annual reports, where securities
  lending income and expense detail actually appear.

Text extraction, chunking, and BM25 ranking are deliberately imported from
``edgar_filings`` rather than reimplemented — a fund prospectus is the same
shape of problem as a 10-K (one large HTML document, no reliable heading
structure), and two copies of a ranking function would drift.

**The caveat that matters:** these documents are filed by the *trust*, and
a trust holds many funds. Vanguard Index Funds files one 485BPOS covering
dozens of series. So a passage retrieved here is guaranteed to come from a
real document filed by the registrant behind the ticker, but is *not*
guaranteed to describe that specific fund rather than a sibling. Every
result therefore carries the registrant name and a ``scope_warning``, and
callers must confirm the passage names the fund before citing it as its
own. Silently presenting a sibling fund's expense ratio would be exactly
the fabrication this project exists to prevent.
"""

from __future__ import annotations

from typing import Any

from src.tools.edgar_client import fetch_text, get_submissions
from src.tools.edgar_filings import _BM25, LiveChunk, _html_to_text, _tokenize, _windowed_chunks
from src.tools.fund_profile import get_fund_name
from src.tools.fund_registry import resolve_fund

# Words that appear in nearly every fund name in a trust prospectus, so they
# do nothing to tell one series apart from its siblings.
_GENERIC_NAME_WORDS = {
    "fund", "funds", "etf", "etfs", "shares", "share", "class", "trust",
    "index", "inc", "the", "of", "and", "portfolio",
}

# Sequenced by density of useful prospectus content per byte fetched.
FUND_TEXT_FORMS = ("497K", "485BPOS", "N-CSR")

# Fetching several multi-megabyte prospectuses is the slow part of any fund
# question, so cap how many documents one search pulls.
_MAX_DOCUMENTS = 3


def list_fund_filings(
    cik: str, forms: tuple[str, ...] = FUND_TEXT_FORMS, limit: int = 40
) -> list[dict[str, Any]]:
    """Return recent filings for a trust CIK, filtered to the given form types."""
    submissions = get_submissions(cik)
    recent = submissions["filings"]["recent"]
    registrant = submissions.get("name", "")

    out: list[dict[str, Any]] = []
    cik_int = str(int(cik))  # EDGAR document URLs use the un-padded CIK
    for i, form in enumerate(recent["form"]):
        if form not in forms:
            continue
        accession = recent["accessionNumber"][i]
        primary_doc = recent["primaryDocument"][i]
        if not primary_doc:
            continue
        out.append(
            {
                "form": form,
                "registrant": registrant,
                "filing_date": recent["filingDate"][i],
                "report_date": recent["reportDate"][i],
                "accession_number": accession,
                "url": (
                    f"https://www.sec.gov/Archives/edgar/data/{cik_int}/"
                    f"{accession.replace('-', '')}/{primary_doc}"
                ),
            }
        )
        if len(out) >= limit:
            break
    return out


def _latest_per_form(filings: list[dict[str, Any]], forms: tuple[str, ...]) -> list[dict[str, Any]]:
    """Pick the most recent filing of each form type, by the forms' priority."""
    picked: list[dict[str, Any]] = []
    for form in forms:
        for filing in filings:  # already newest-first as EDGAR returns them
            if filing["form"] == form:
                picked.append(filing)
                break
        if len(picked) >= _MAX_DOCUMENTS:
            break
    return picked


def _focus_terms(ticker: str, fund_name: str | None) -> list[str]:
    """Distinctive tokens that mark a passage as being about *this* fund."""
    terms = [ticker.lower()]
    for token in _tokenize(fund_name or ""):
        if token not in _GENERIC_NAME_WORDS and len(token) > 2:
            terms.append(token)
    return terms


def _focus_rerank(hits: list[dict[str, Any]], terms: list[str], top_k: int) -> list[dict[str, Any]]:
    """Re-rank BM25 hits toward passages that actually name this fund.

    A trust prospectus describes many sibling funds in near-identical
    language, so a pure relevance ranking happily returns boilerplate about
    "the funds" in general. Boosting passages that carry the fund's own
    distinctive name tokens is what makes a retrieved fee or objective
    likely to be *this* fund's. It is a bias, not a guarantee — the
    scope_warning stands either way.
    """
    if not terms:
        return hits[:top_k]

    for hit in hits:
        text = hit["text"].lower()
        matched = [t for t in terms if t in text]
        hit["focus_terms_matched"] = matched
        hit["focus_boost"] = round(1.0 + 0.5 * (len(matched) / len(terms)), 4)
        hit["score"] = round(hit["score"] * hit["focus_boost"], 4)

    hits.sort(key=lambda h: h["score"], reverse=True)
    return hits[:top_k]


def search_fund_filings(ticker: str, query: str, top_k: int = 3) -> dict[str, Any]:
    """Search a fund's prospectus and report filings for passages matching a query.

    Returns ``{"status": "ok", "fund", "documents", "results"}``, or a
    ``{"status", "reason"}`` refusal if the ticker isn't a supported fund.
    Every result carries the form, filing date, and source URL of the real
    document it came from.
    """
    resolution = resolve_fund(ticker)
    if resolution["status"] != "ok":
        return resolution

    symbol = resolution["ticker"]
    cik = resolution["cik"]
    filings = list_fund_filings(cik)
    if not filings:
        return {
            "status": "no_filings",
            "ticker": resolution["ticker"],
            "reason": (
                f"No {', '.join(FUND_TEXT_FORMS)} filings found for CIK {cik}. Without a "
                "prospectus this project has nothing to cite for this fund."
            ),
        }

    documents = _latest_per_form(filings, FUND_TEXT_FORMS)
    registrant = documents[0]["registrant"]
    form_by_url = {d["url"]: d["form"] for d in documents}

    chunks: list[LiveChunk] = []
    fetch_errors: list[dict[str, str]] = []
    for doc in documents:
        try:
            html = fetch_text(doc["url"], cache_key=f"fundfiling_{cik}_{doc['accession_number']}")
        except Exception as exc:  # one unreachable document shouldn't sink the search
            fetch_errors.append({"form": doc["form"], "url": doc["url"], "error": str(exc)})
            continue
        for window in _windowed_chunks(_html_to_text(html)):
            chunks.append(
                LiveChunk(
                    ticker=resolution["ticker"],
                    company=registrant,
                    source_url=doc["url"],
                    filing_date=doc["filing_date"],
                    text=window,
                    tokens=_tokenize(window),
                )
            )

    if not chunks:
        return {
            "status": "no_text",
            "ticker": resolution["ticker"],
            "reason": "Could not extract readable text from this fund's filings.",
            "fetch_errors": fetch_errors,
        }

    # Rank a wide candidate set, then bias it toward passages naming this
    # fund before cutting to top_k — re-ranking after the cut would be too
    # late, since the boilerplate would already have crowded the list.
    fund_name = get_fund_name(symbol)
    candidates = _BM25(chunks).search(query, top_k=max(top_k * 8, 24))
    ranked = _focus_rerank(candidates, _focus_terms(symbol, fund_name), top_k)

    # _BM25 emits score/ticker/source_url/filing_date/text; the form label is
    # recovered from the URL rather than smuggled through a chunk field.
    results = [
        {**hit, "form": form_by_url.get(hit["source_url"], "unknown"), "source": "filing"}
        for hit in ranked
    ]

    return {
        "status": "ok",
        "fund": {
            "ticker": resolution["ticker"],
            "cik": cik,
            "series_id": resolution["series_id"],
            "class_id": resolution["class_id"],
            "registrant": registrant,
        },
        "scope_warning": (
            f"These documents are filed by {registrant}, which registers many funds. Confirm a "
            f"passage names {resolution['ticker']} (series {resolution['series_id']}) before "
            "citing it as this fund's — a trust prospectus also describes sibling funds."
        ),
        "documents": [
            {"form": d["form"], "filing_date": d["filing_date"], "url": d["url"]} for d in documents
        ],
        "fetch_errors": fetch_errors,
        "results": results,
    }
