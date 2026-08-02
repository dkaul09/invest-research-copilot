"""The Stop hook must block advice language and allow research framing."""

import json
import subprocess
import sys
from pathlib import Path

HOOK_PATH = Path(__file__).resolve().parents[1] / ".claude" / "hooks" / "check_output_language.py"


def run_hook(message: str) -> dict | None:
    result = subprocess.run(
        [sys.executable, str(HOOK_PATH)],
        input=json.dumps({"message": message}),
        capture_output=True,
        text=True,
        check=True,
    )
    stdout = result.stdout.strip()
    return json.loads(stdout) if stdout else None


def test_blocks_you_should_buy():
    decision = run_hook("Given the metrics, you should buy AAPL now.")
    assert decision is not None
    assert decision["decision"] == "block"


def test_blocks_sell_immediately():
    decision = run_hook("Sell immediately to lock in gains.")
    assert decision is not None
    assert decision["decision"] == "block"


def test_blocks_place_this_trade():
    decision = run_hook("You could place this trade before earnings.")
    assert decision is not None
    assert decision["decision"] == "block"


def test_allows_research_framed_response():
    text = (
        "## Research Note\nThis is a watchlist candidate; margins improved but "
        "leverage needs more evidence before drawing a conclusion. Open questions "
        "remain about China exposure."
    )
    decision = run_hook(text)
    assert decision is None


def test_allows_risk_summary_without_advice():
    text = "Risks: elevated capex, competitive pressure. Open questions: AI ROI timeline."
    decision = run_hook(text)
    assert decision is None
