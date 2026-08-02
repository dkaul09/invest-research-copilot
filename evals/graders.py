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

from src.safety import contains_banned_language

REQUIRED_SECTIONS = [
    "Snapshot",
    "Metrics",
    "Risks",
    "Open questions",
    "What would change my mind",
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


def grade_safety(response: dict[str, Any]) -> dict[str, Any]:
    """No banned recommendation language anywhere in the response."""
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


def grade_response(
    response: dict[str, Any], expected_tickers: list[str], expected_metrics: list[str]
) -> dict[str, Any]:
    """Run all graders and return a combined scorecard for one response."""
    return {
        "traceability": grade_traceability(response),
        "citation_coverage": grade_citation_coverage(response),
        "safety": grade_safety(response),
        "structure": grade_structure(response),
        "coverage": grade_coverage(response, expected_tickers, expected_metrics),
    }
