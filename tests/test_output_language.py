"""The Stop hook must block fabricated trade-execution claims, and must
allow both plain research framing and a stated investment view/rating —
opinions are allowed here, only claiming an action was actually taken is
not."""

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


def test_blocks_claim_of_placed_trade():
    decision = run_hook("I've placed this trade for you.")
    assert decision is not None
    assert decision["decision"] == "block"


def test_blocks_claim_of_order_filled():
    decision = run_hook("Your order was filled at $150.")
    assert decision is not None
    assert decision["decision"] == "block"


def test_blocks_claim_of_having_bought():
    decision = run_hook("I bought 10 shares of AAPL on your behalf.")
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


def test_allows_stated_investment_view():
    text = (
        "## View\nBullish on MSFT: gross margin of 69.8% and 15.7% revenue growth "
        "support the current valuation, though AI capex is a risk to watch. "
        "You should consider MSFT a buy candidate on this evidence."
    )
    decision = run_hook(text)
    assert decision is None
