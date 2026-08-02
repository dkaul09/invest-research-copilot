"""The PreToolUse hook must deny any tool call shaped like order execution."""

import json
import subprocess
import sys
from pathlib import Path

HOOK_PATH = Path(__file__).resolve().parents[1] / ".claude" / "hooks" / "block_trading_tools.py"


def run_hook(payload: dict) -> dict | None:
    result = subprocess.run(
        [sys.executable, str(HOOK_PATH)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        check=True,
    )
    stdout = result.stdout.strip()
    return json.loads(stdout) if stdout else None


def test_denies_submit_order_tool_name():
    decision = run_hook({"tool_name": "submit_order", "tool_input": {"ticker": "AAPL"}})
    assert decision is not None
    assert decision["hookSpecificOutput"]["permissionDecision"] == "deny"


def test_denies_buy_in_arguments():
    decision = run_hook({"tool_name": "some_tool", "tool_input": {"action": "buy", "ticker": "MSFT"}})
    assert decision is not None
    assert decision["hookSpecificOutput"]["permissionDecision"] == "deny"


def test_denies_cancel_order():
    decision = run_hook({"tool_name": "cancel_order", "tool_input": {}})
    assert decision is not None
    assert decision["hookSpecificOutput"]["permissionDecision"] == "deny"


def test_allows_benign_read_tool():
    decision = run_hook({"tool_name": "get_portfolio_snapshot", "tool_input": {}})
    assert decision is None


def test_allows_research_question_about_a_company_selling_a_division():
    # A benign research-shaped tool call should not be denied just because
    # the underlying question is about a company's business decision, as
    # long as the tool name/args themselves don't match the pattern.
    decision = run_hook(
        {"tool_name": "search_filings", "tool_input": {"query": "wholesale channel transition"}}
    )
    assert decision is None
