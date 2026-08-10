"""Read-only MCP client for Robinhood's agent endpoint.

This module is the security boundary of the live-account feature, and it is
worth being explicit about why it has to exist at all.

``adapters/base.py`` states the intended design: a brokerage credential
should be scoped read-only *at the provider*, so that even a bug in this
codebase cannot act on an account. Robinhood does not offer that — its
OAuth metadata publishes a single scope, ``internal``. The token the
dashboard holds can, as far as the provider is concerned, do anything the
account allows. So the guarantee has to be reconstructed on this side, and
this is the one place it lives.

Three layers, deliberately redundant:

1. **An allowlist of four read tools.** ``call_tool`` refuses any name not
   in ``READ_ONLY_TOOLS``. It is an allowlist rather than a denylist of
   dangerous verbs, because a denylist fails open the moment the remote
   server adds a tool nobody here anticipated.
2. **No passthrough.** Nothing in this module accepts a caller-supplied
   tool name from an HTTP route. The adapter above it calls four named
   functions; there is no generic "call any tool" path reachable from the
   web layer.
3. **The account itself.** The default account reports
   ``agentic_allowed: false``, meaning Robinhood refuses agent-initiated
   activity on it regardless of what this code does. That is the only
   provider-side guarantee available, and it is the reason this feature is
   acceptable at all rather than merely convenient.

If a future change needs a fifth tool, adding it to the allowlist should
require reading this docstring and deciding the tool is genuinely
read-only. That friction is the point.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any

from src.adapters.rh_oauth import RESOURCE, get_access_token

# Every tool this project may ever call on the brokerage. Each one reads;
# none creates, modifies, or cancels anything. Adding to this set is a
# security decision, not a convenience.
READ_ONLY_TOOLS = frozenset(
    {
        "get_accounts",
        "get_portfolio",
        "get_equity_positions",
        "get_equity_quotes",
    }
)


class RobinhoodToolNotAllowed(Exception):
    """Raised when something asks for a tool outside the read-only allowlist."""


class RobinhoodMCPError(Exception):
    """Raised when the MCP endpoint returns an error or an unreadable response."""


def _parse_response(raw: bytes) -> dict[str, Any]:
    """Parse a JSON or SSE-framed JSON-RPC response.

    Streamable-HTTP MCP servers may answer a single request with either
    ``application/json`` or an SSE stream carrying one ``data:`` frame.
    """
    text = raw.decode("utf-8", errors="replace").strip()
    if not text:
        raise RobinhoodMCPError("Empty response from the Robinhood MCP endpoint.")

    if text.startswith("{"):
        return json.loads(text)

    for line in text.splitlines():
        line = line.strip()
        if line.startswith("data:"):
            payload = line[len("data:") :].strip()
            if payload:
                return json.loads(payload)
    raise RobinhoodMCPError(f"Could not parse MCP response: {text[:200]}")


def _rpc(method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    """Make one JSON-RPC call against the MCP endpoint with a bearer token."""
    body = json.dumps(
        {"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}}
    ).encode()
    request = urllib.request.Request(
        RESOURCE,
        data=body,
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            "Authorization": f"Bearer {get_access_token()}",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            payload = _parse_response(response.read())
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:300]
        if exc.code in (401, 403):
            raise RobinhoodMCPError(
                "Robinhood rejected the dashboard's credentials — reconnect the account."
            ) from exc
        raise RobinhoodMCPError(f"Robinhood MCP returned HTTP {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise RobinhoodMCPError(f"Could not reach Robinhood: {exc}") from exc

    if "error" in payload:
        raise RobinhoodMCPError(f"Robinhood MCP error: {payload['error']}")
    return payload.get("result", {})


def call_tool(name: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
    """Call a read-only Robinhood tool. Refuses anything outside the allowlist.

    The check is first, before any network call and before the token is
    read, so a disallowed name never reaches an authenticated request.
    """
    if name not in READ_ONLY_TOOLS:
        raise RobinhoodToolNotAllowed(
            f"'{name}' is not in this project's read-only allowlist "
            f"({', '.join(sorted(READ_ONLY_TOOLS))}). This project only ever reads "
            "brokerage data; it has no path to act on an account."
        )

    result = _rpc("tools/call", {"name": name, "arguments": arguments or {}})

    # MCP returns tool output as content blocks; the Robinhood server sends
    # a single JSON text block.
    for block in result.get("content", []):
        if block.get("type") == "text":
            try:
                return json.loads(block["text"])
            except json.JSONDecodeError:
                return {"text": block["text"]}
    if "structuredContent" in result:
        return result["structuredContent"]
    raise RobinhoodMCPError(f"No readable content in the response to '{name}'.")


def get_accounts() -> list[dict[str, Any]]:
    return call_tool("get_accounts").get("data", {}).get("accounts", [])


def get_portfolio(account_number: str) -> dict[str, Any]:
    return call_tool("get_portfolio", {"account_number": account_number}).get("data", {})


def get_equity_positions(account_number: str) -> list[dict[str, Any]]:
    payload = call_tool("get_equity_positions", {"account_number": account_number})
    return payload.get("data", {}).get("positions", [])


def get_equity_quotes(symbols: list[str]) -> dict[str, dict[str, Any]]:
    """Return {symbol: {price, previous_close}} for the given symbols."""
    if not symbols:
        return {}
    payload = call_tool("get_equity_quotes", {"symbols": symbols})
    quotes: dict[str, dict[str, Any]] = {}
    for entry in payload.get("data", {}).get("results", []):
        quote = entry.get("quote") or {}
        symbol = quote.get("symbol")
        if not symbol:
            continue
        close = (entry.get("close") or {}).get("price")
        quotes[symbol] = {
            "price": _as_float(quote.get("last_trade_price")),
            "previous_close": _as_float(
                close if close is not None else quote.get("previous_close")
            ),
            "state": quote.get("state"),
            "has_traded": quote.get("has_traded"),
        }
    return quotes


def _as_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
