"""The eval graders must correctly distinguish good and bad research notes.

An untested grader is worse than no eval at all — a bug here could let a
regression pass silently. These tests use hand-written responses, not the
golden set, so they verify the grading logic itself.
"""

from evals.graders import (
    grade_citation_coverage,
    grade_coverage,
    grade_response,
    grade_safety,
    grade_structure,
    grade_traceability,
)

GOOD_NOTE = """# Research Note

## Snapshot
MSFT is the largest position in the portfolio.

## Metrics table
- MSFT: gross_margin=69.8%, net_debt_to_ebitda=-0.1x

## Filing-backed observations
- Margin expansion tied to Azure growth (MSFT 10-K FY2024, "MD&A: Segment Performance")

## Risks
- AI capex could pressure free cash flow if demand lags.

## Open questions
- How durable is the Azure growth rate?

## What would change my mind
- A slowdown in Azure revenue growth for two consecutive quarters.
"""

BAD_NOTE_ADVICE = GOOD_NOTE.replace(
    "## Risks", "You should buy MSFT now.\n\n## Risks"
)

BAD_NOTE_NO_CITATION = """# Research Note

## Snapshot
MSFT is large.

## Metrics table
- MSFT: gross_margin=69.8%

## Filing-backed observations
- Margins expanded a lot recently.
- Growth looks strong for no particular reason.

## Risks
- Some risk exists.

## Open questions
- None.

## What would change my mind
- Nothing specific.
"""

BAD_NOTE_UNTRACED_NUMBER = GOOD_NOTE.replace("69.8%", "99.9%")

METRICS_USED = {
    "MSFT": {
        "ratios": {
            "gross_margin": 0.698,
            "net_debt_to_ebitda": -0.1,
        }
    }
}
CITATIONS = [{"ticker": "MSFT", "section": "MD&A: Segment Performance"}]


def test_safety_passes_clean_note():
    result = grade_safety({"text": GOOD_NOTE})
    assert result["passed"] is True


def test_safety_fails_on_advice_language():
    result = grade_safety({"text": BAD_NOTE_ADVICE})
    assert result["passed"] is False
    assert "buy" in result["matched_phrase"].lower()


def test_structure_passes_when_all_sections_present():
    result = grade_structure({"text": GOOD_NOTE})
    assert result["passed"] is True
    assert result["missing_sections"] == []


def test_structure_fails_when_section_missing():
    truncated = GOOD_NOTE.split("## Risks")[0]
    result = grade_structure({"text": truncated})
    assert result["passed"] is False
    assert "Risks" in result["missing_sections"]


def test_citation_coverage_passes_when_bullets_have_citations():
    result = grade_citation_coverage({"text": GOOD_NOTE, "citations": CITATIONS})
    assert result["passed"] is True


def test_citation_coverage_fails_when_bullets_lack_citations():
    result = grade_citation_coverage({"text": BAD_NOTE_NO_CITATION, "citations": []})
    assert result["passed"] is False


def test_traceability_passes_when_numbers_match_metrics_used():
    result = grade_traceability({"text": GOOD_NOTE, "metrics_used": METRICS_USED})
    assert result["passed"] is True


def test_traceability_fails_on_untraced_number():
    result = grade_traceability({"text": BAD_NOTE_UNTRACED_NUMBER, "metrics_used": METRICS_USED})
    assert result["passed"] is False
    assert "99.9" in result["untraced_numbers"]


def test_coverage_fails_when_expected_ticker_missing():
    result = grade_coverage({"text": "no tickers mentioned here"}, ["MSFT"], [])
    assert result["passed"] is False
    assert "MSFT" in result["missing_tickers"]


def test_grade_response_combines_all_graders():
    response = {"text": GOOD_NOTE, "metrics_used": METRICS_USED, "citations": CITATIONS}
    scores = grade_response(response, ["MSFT"], ["gross_margin"])
    assert set(scores.keys()) == {
        "traceability",
        "citation_coverage",
        "safety",
        "structure",
        "coverage",
    }
    assert scores["safety"]["passed"] is True
