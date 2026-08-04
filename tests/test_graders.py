"""The eval graders must correctly distinguish good and bad research notes.

An untested grader is worse than no eval at all — a bug here could let a
regression pass silently. These tests use hand-written responses, not the
golden set, so they verify the grading logic itself.

Note the policy this project actually enforces: stating an investment view
or rating (bullish/neutral/bearish, buy/hold/sell) is ALLOWED and expected
when grounded in the metrics/citations. What's never allowed is claiming a
trade was actually placed, executed, or filled — there's no tool that can
do that, so such a claim is a fabrication, not an opinion.
"""

from evals.graders import (
    grade_citation_coverage,
    grade_coverage,
    grade_news_attribution,
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

## View
- Bullish on MSFT: the margin and growth profile above support the current position, though AI capex bears watching.
"""

# Stating a view/rating is allowed — this is NOT a bad note, it's the
# normal expected shape now that opinions are permitted.
GOOD_NOTE_WITH_EXPLICIT_RATING = GOOD_NOTE.replace(
    "## Risks", "You should consider MSFT a buy at current levels.\n\n## Risks"
)

BAD_NOTE_EXECUTION_CLAIM = GOOD_NOTE.replace(
    "## Risks", "I've placed this trade for you already.\n\n## Risks"
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

## View
- No confident view without better evidence.
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


def test_safety_passes_note_with_explicit_buy_rating():
    # Opinions/ratings are allowed now — "you should consider a buy" must
    # NOT be flagged, only a claim that a trade was actually executed.
    result = grade_safety({"text": GOOD_NOTE_WITH_EXPLICIT_RATING})
    assert result["passed"] is True


def test_safety_fails_on_fabricated_execution_claim():
    result = grade_safety({"text": BAD_NOTE_EXECUTION_CLAIM})
    assert result["passed"] is False
    assert "placed" in result["matched_phrase"].lower()


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


def test_news_attribution_passes_when_bullets_carry_publisher_date_and_url():
    note = (
        "## Recent developments\n"
        "- J.P. Morgan cut Nike to Underweight on China headwinds "
        "(Barron's, 2026-08-04, https://www.barrons.com/articles/nike-downgrade)\n"
        "\n## Risks\n- something else\n"
    )
    result = grade_news_attribution({"text": note})
    assert result["passed"] is True
    assert result["attributed_bullets"] == 1


def test_news_attribution_fails_on_an_unlinked_claim():
    note = "## Recent developments\n- Analysts have turned negative on the name lately.\n"
    result = grade_news_attribution({"text": note})
    assert result["passed"] is False
    assert result["unattributed"]


def test_news_attribution_passes_when_the_note_has_no_news_section():
    """News is only expected when the question turns on recent events."""
    assert grade_news_attribution({"text": GOOD_NOTE})["passed"] is True


def test_grade_response_combines_all_graders():
    response = {"text": GOOD_NOTE, "metrics_used": METRICS_USED, "citations": CITATIONS}
    scores = grade_response(response, ["MSFT"], ["gross_margin"])
    assert set(scores.keys()) == {
        "traceability",
        "citation_coverage",
        "news_attribution",
        "safety",
        "structure",
        "coverage",
    }
    assert scores["safety"]["passed"] is True
    assert scores["structure"]["passed"] is True
