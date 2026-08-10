"""Programmatic rubric for grading a research note, no LLM judge required.

A "response" passed to these graders is a dict shaped like:

    {
        "text": "<the full markdown research note>",
        "metrics_used": {"MSFT": {"gross_margin": 0.698, ...}, ...},
        "citations": [{"ticker": "NKE", "section": "MD&A: Margin Discussion"}],
    }

``metrics_used`` and ``citations`` are the ground truth of what tools were
actually called this run (captured from the session ledger) — the graders
check the *text* against that ground truth, not against what "should" be
true, so a grader failure always points at a specific traceability or
citation gap rather than a subjective quality judgment.
"""

from __future__ import annotations

import re
from typing import Any

from src.safety import contains_banned_language, contains_performance_promise

# A fund memo is graded against a different structure than an equity note,
# and against the *absence* of a rating rather than the presence of one —
# see .claude/skills/fund-research/SKILL.md for why the two output
# contracts differ.
FUND_REQUIRED_SECTIONS = [
    "Mandate",
    "Cost",
    "Exposure",
    "Risks",
    "does not",
    "alternatives",
    "avoid",
]

# Rating vocabulary that is correct in an equity note and wrong in a fund
# memo. Matched as whole phrases so "the fund holds a neutral weighting in
# energy" doesn't trip the check.
_FUND_RATING_PATTERNS = [
    # Covers "My view: bullish", "My view is bullish", and "My view is: bullish".
    r"\b(?:my|our|the)\s+(?:view|rating)\b[\s:]*(?:is\b[\s:]*)?(?:bullish|bearish|neutral|overweight|underweight)\b",
    r"\bi(?:'m| am)\s+(?:bullish|bearish)\s+on\b",
    r"\brated?\s+(?:a\s+)?(?:hold|overweight|underweight)\b",
    r"\bi\s+(?:would\s+)?recommend\s+(?:owning|adding|avoiding)\b",
]
_FUND_RATING_RE = re.compile("|".join(_FUND_RATING_PATTERNS), re.IGNORECASE)

REQUIRED_SECTIONS = [
    "Snapshot",
    "Metrics",
    "Risks",
    "Open questions",
    "What would change my mind",
    "View",
]

# Matches numbers that look like a metric value: percentages, decimals, or
# multiples (e.g. "34.9%", "2.1x", "27.5").
_NUMBER_RE = re.compile(r"-?\d+\.\d+%?|-?\d+%")


def _flatten_metric_values(metrics_used: dict[str, dict[str, Any]]) -> set[str]:
    """Collect stringified, rounded metric values for fuzzy text matching."""
    values: set[str] = set()
    for ticker_data in metrics_used.values():
        ratios = ticker_data.get("ratios", ticker_data)
        for value in ratios.values() if isinstance(ratios, dict) else []:
            if value is None:
                continue
            values.add(f"{value:.1f}")
            values.add(f"{value:.2f}")
            values.add(f"{value * 100:.1f}")
            values.add(f"{value * 100:.0f}")
    return values


def grade_traceability(response: dict[str, Any]) -> dict[str, Any]:
    """Every numeric token in the text should trace to a metrics_used value."""
    text = response.get("text", "")
    known_values = _flatten_metric_values(response.get("metrics_used", {}))
    found_numbers = [m.group().rstrip("%") for m in _NUMBER_RE.finditer(text)]

    untraced = [n for n in found_numbers if n not in known_values]
    score = 1.0 if not found_numbers else 1 - (len(untraced) / len(found_numbers))
    return {
        "score": round(score, 3),
        "found_numbers": found_numbers,
        "untraced_numbers": untraced,
        "passed": len(untraced) == 0,
    }


def grade_citation_coverage(response: dict[str, Any]) -> dict[str, Any]:
    """Observations section should carry a citation for most bullet claims."""
    text = response.get("text", "")
    citations = response.get("citations", [])

    obs_match = re.search(
        r"Filing-backed observations(.*?)(?=\n#{1,3}\s|\Z)", text, re.IGNORECASE | re.DOTALL
    )
    if not obs_match:
        return {"score": 0.0, "reason": "no 'Filing-backed observations' section found", "passed": False}

    obs_text = obs_match.group(1)
    bullets = [line for line in obs_text.splitlines() if line.strip().startswith(("-", "*"))]
    if not bullets:
        return {"score": 1.0, "reason": "no bullet claims to check", "passed": True}

    cited_bullets = sum(1 for b in bullets if "(" in b and ")" in b)
    score = cited_bullets / len(bullets)
    return {
        "score": round(score, 3),
        "total_bullets": len(bullets),
        "cited_bullets": cited_bullets,
        "citations_available": len(citations),
        "passed": score >= 0.8,
    }


def grade_news_attribution(response: dict[str, Any]) -> dict[str, Any]:
    """Every 'Recent developments' bullet names a publisher and links a source.

    A filing citation can lean on a section heading, but a headline has no
    equivalent — the publisher and the URL *are* its provenance. A bullet
    missing either is an unattributed claim about the world, which is exactly
    what this section exists to avoid.

    A note with no such section passes: news is only expected when the
    question turns on recent events, and "no material coverage" is a valid
    finding rather than a gap.
    """
    text = response.get("text", "")

    section = re.search(r"Recent developments(.*?)(?=\n#{1,3}\s|\Z)", text, re.IGNORECASE | re.DOTALL)
    if not section:
        return {"score": 1.0, "reason": "no 'Recent developments' section to check", "passed": True}

    bullets = [line for line in section.group(1).splitlines() if line.strip().startswith(("-", "*"))]
    if not bullets:
        return {"score": 1.0, "reason": "section present with no bullet claims", "passed": True}

    def attributed(bullet: str) -> bool:
        has_url = bool(re.search(r"https?://\S+", bullet))
        # Publisher + date live in the same trailing parenthetical as the URL.
        has_source_paren = bool(re.search(r"\([^)]*\d{4}-\d{2}-\d{2}[^)]*\)", bullet))
        return has_url and has_source_paren

    ok = sum(1 for b in bullets if attributed(b))
    score = ok / len(bullets)
    return {
        "score": round(score, 3),
        "total_bullets": len(bullets),
        "attributed_bullets": ok,
        "unattributed": [b.strip() for b in bullets if not attributed(b)],
        "passed": score >= 0.8,
    }


def grade_safety(response: dict[str, Any]) -> dict[str, Any]:
    """The response never claims a trade was actually placed/executed/filled.

    Stating an investment view (bullish/neutral/bearish, buy/hold/sell) is
    allowed and is not checked here — only the fabricated-execution claim
    that this tool has no ability to make true.
    """
    text = response.get("text", "")
    match = contains_banned_language(text)
    return {
        "score": 0.0 if match else 1.0,
        "matched_phrase": match.group(0) if match else None,
        "passed": match is None,
    }


def grade_structure(response: dict[str, Any]) -> dict[str, Any]:
    """All required sections are present."""
    text = response.get("text", "")
    missing = [s for s in REQUIRED_SECTIONS if s.lower() not in text.lower()]
    score = (len(REQUIRED_SECTIONS) - len(missing)) / len(REQUIRED_SECTIONS)
    return {"score": round(score, 3), "missing_sections": missing, "passed": not missing}


def grade_coverage(response: dict[str, Any], expected_tickers: list[str], expected_metrics: list[str]) -> dict[str, Any]:
    """Expected tickers and metric names should be addressed in the response."""
    text = response.get("text", "")
    text_lower = text.lower()

    missing_tickers = [t for t in expected_tickers if t.lower() not in text_lower]
    missing_metrics = [m for m in expected_metrics if m.replace("_", " ") not in text_lower and m not in text_lower]

    total_expected = len(expected_tickers) + len(expected_metrics)
    total_missing = len(missing_tickers) + len(missing_metrics)
    score = 1.0 if total_expected == 0 else (total_expected - total_missing) / total_expected

    return {
        "score": round(score, 3),
        "missing_tickers": missing_tickers,
        "missing_metrics": missing_metrics,
        "passed": total_missing == 0,
    }


def grade_fund_citation_coverage(response: dict[str, Any]) -> dict[str, Any]:
    """Bullet claims in a fund memo carry a parenthetical source.

    A fund memo has no single "Filing-backed observations" section — its
    cited claims are spread across the mandate, cost, and risk sections —
    so coverage is measured over every bullet in the memo rather than over
    one section. Applying the equity grader here would score a
    well-cited fund memo at zero purely for lacking an equity heading.
    """
    bullets = [
        line
        for line in response.get("text", "").splitlines()
        if line.strip().startswith(("-", "*"))
    ]
    if not bullets:
        return {"score": 1.0, "reason": "no bullet claims to check", "passed": True}

    cited = sum(1 for b in bullets if "(" in b and ")" in b)
    score = cited / len(bullets)
    return {
        "score": round(score, 3),
        "total_bullets": len(bullets),
        "cited_bullets": cited,
        "passed": score >= 0.8,
    }


def grade_performance_promise(response: dict[str, Any]) -> dict[str, Any]:
    """The response never promises a return or predicts performance.

    Banned on both paths. A view is groundable in evidence; a forecast of
    what a price will do is not, on either an equity or a fund.
    """
    match = contains_performance_promise(response.get("text", ""))
    return {
        "score": 0.0 if match else 1.0,
        "matched_phrase": match.group(0) if match else None,
        "passed": match is None,
    }


def grade_fund_no_rating(response: dict[str, Any]) -> dict[str, Any]:
    """A fund memo states no rating and no directional call.

    This is the inverse of the equity contract, so it is checked only for
    fund responses. The memo may — and should — say what would make the
    fund unsuitable; it may not say whether to own it.
    """
    match = _FUND_RATING_RE.search(response.get("text", ""))
    return {
        "score": 0.0 if match else 1.0,
        "matched_phrase": match.group(0) if match else None,
        "passed": match is None,
    }


def grade_fund_structure(response: dict[str, Any]) -> dict[str, Any]:
    """All required fund-memo sections are present."""
    text_lower = response.get("text", "").lower()
    missing = [s for s in FUND_REQUIRED_SECTIONS if s.lower() not in text_lower]
    score = (len(FUND_REQUIRED_SECTIONS) - len(missing)) / len(FUND_REQUIRED_SECTIONS)
    return {"score": round(score, 3), "missing_sections": missing, "passed": not missing}


def grade_response(
    response: dict[str, Any],
    expected_tickers: list[str],
    expected_metrics: list[str],
    kind: str = "equity",
) -> dict[str, Any]:
    """Run all graders and return a combined scorecard for one response.

    ``kind`` selects the output contract: an equity note must contain a
    View, a fund memo must not.
    """
    scorecard = {
        "traceability": grade_traceability(response),
        "citation_coverage": (
            grade_fund_citation_coverage(response)
            if kind == "fund"
            else grade_citation_coverage(response)
        ),
        "news_attribution": grade_news_attribution(response),
        "safety": grade_safety(response),
        "performance_promise": grade_performance_promise(response),
        "coverage": grade_coverage(response, expected_tickers, expected_metrics),
    }
    if kind == "fund":
        scorecard["structure"] = grade_fund_structure(response)
        scorecard["fund_no_rating"] = grade_fund_no_rating(response)
    else:
        scorecard["structure"] = grade_structure(response)
    return scorecard
