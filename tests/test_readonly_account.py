"""No adapter, tool, or MCP surface exposes a write/mutating capability."""

import inspect

from src.adapters.base import PortfolioAdapter
from src.tools.mock_portfolio import MockPortfolioAdapter, load_default_adapter

ALLOWED_METHOD_NAMES = {"get_snapshot", "get_holding"}


def test_portfolio_adapter_protocol_only_exposes_read_methods():
    protocol_methods = {
        name
        for name, _ in inspect.getmembers(PortfolioAdapter, predicate=inspect.isfunction)
        if not name.startswith("_")
    }
    assert protocol_methods == ALLOWED_METHOD_NAMES


def test_mock_adapter_has_no_write_methods():
    public_methods = {
        name
        for name, _ in inspect.getmembers(MockPortfolioAdapter, predicate=inspect.isfunction)
        if not name.startswith("_")
    }
    assert public_methods == ALLOWED_METHOD_NAMES


def test_default_adapter_is_read_only_mock():
    adapter = load_default_adapter()
    assert isinstance(adapter, MockPortfolioAdapter)
    snapshot = adapter.get_snapshot()
    assert "holdings" in snapshot and "cash" in snapshot


def test_mcp_server_exposes_no_write_shaped_tool_names():
    # Inspect the source directly rather than the runtime object: FastMCP
    # wraps decorated functions, so this is the more robust way to assert
    # no tool name in the file resembles a write/execute operation.
    import ast
    from pathlib import Path

    source_path = Path(__file__).resolve().parents[1] / "src" / "mcp_server.py"
    tree = ast.parse(source_path.read_text(encoding="utf-8"))
    tool_names = [node.name for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)]

    assert tool_names, "expected at least one tool function in mcp_server.py"
    banned_substrings = ("buy", "sell", "order", "trade", "execute", "cancel")
    offenders = [n for n in tool_names if any(b in n.lower() for b in banned_substrings)]
    assert offenders == []
