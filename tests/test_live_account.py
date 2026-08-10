"""Tests for the live brokerage adapter.

The subject here is the security boundary, not the arithmetic. Robinhood
publishes no read-only OAuth scope, so the read-only guarantee is
reconstructed in this codebase by an allowlist — which means the allowlist
itself has to be tested, and tested for the failure mode that matters: a
tool nobody anticipated must be refused by default.

Nothing here touches the network or reads real credentials.
"""

from __future__ import annotations

import json
import time

import pytest

from src.adapters import rh_mcp_client, rh_oauth
from src.adapters.rh_mcp_client import RobinhoodToolNotAllowed
from src.adapters.robinhood_live import RobinhoodLiveAdapter


class TestReadOnlyAllowlist:
    def test_the_allowlist_contains_only_read_tools(self):
        assert rh_mcp_client.READ_ONLY_TOOLS == {
            "get_accounts",
            "get_portfolio",
            "get_equity_positions",
            "get_equity_quotes",
        }

    @pytest.mark.parametrize(
        "name",
        [
            "place_equity_order",
            "cancel_equity_order",
            "place_option_order",
            "create_watchlist",
            "some_tool_added_next_year",
        ],
    )
    def test_anything_outside_the_allowlist_is_refused(self, name, monkeypatch):
        """An allowlist must fail closed on names nobody anticipated."""

        def explode(*args, **kwargs):
            raise AssertionError("a disallowed tool reached the network")

        monkeypatch.setattr(rh_mcp_client, "_rpc", explode)
        with pytest.raises(RobinhoodToolNotAllowed):
            rh_mcp_client.call_tool(name, {})

    def test_refusal_happens_before_any_token_is_read(self, monkeypatch):
        """A disallowed name must never trigger an authenticated request."""

        def explode(*args, **kwargs):
            raise AssertionError("token was read for a disallowed tool")

        monkeypatch.setattr(rh_mcp_client, "get_access_token", explode)
        monkeypatch.setattr(rh_mcp_client, "_rpc", explode)
        with pytest.raises(RobinhoodToolNotAllowed):
            rh_mcp_client.call_tool("place_equity_order", {})


class TestResponseParsing:
    def test_parses_a_plain_json_body(self):
        assert rh_mcp_client._parse_response(b'{"result": {"ok": true}}')["result"]["ok"] is True

    def test_parses_an_sse_framed_body(self):
        raw = b"event: message\ndata: {\"result\": {\"ok\": true}}\n\n"
        assert rh_mcp_client._parse_response(raw)["result"]["ok"] is True


ACCOUNTS = [
    {"account_number": "111", "is_default": False, "agentic_allowed": True, "nickname": "Agentic"},
    {"account_number": "999", "is_default": True, "agentic_allowed": False},
]
POSITIONS = [
    {
        "symbol": "VOO",
        "quantity": "2.000000",
        "average_buy_price": "700.000000",
        "shares_available_for_sells": "2.000000",
        "shares_held_for_stock_grants": "0.000000",
    },
    {
        "symbol": "NVDA",
        "quantity": "0.500000",
        "average_buy_price": "200.000000",
        "shares_available_for_sells": "0.000000",
        "shares_held_for_stock_grants": "0.500000",
    },
]
QUOTES = {
    "VOO": {"price": 710.0, "previous_close": 700.0},
    "NVDA": {"price": 220.0, "previous_close": 224.0},
}


@pytest.fixture
def live(monkeypatch):
    monkeypatch.setattr(rh_mcp_client, "get_accounts", lambda: ACCOUNTS)
    monkeypatch.setattr(
        rh_mcp_client,
        "get_portfolio",
        lambda account_number: {
            "total_value": "1530.00",
            "cash": "0.00",
            "buying_power": {"buying_power": "0.0000"},
        },
    )
    monkeypatch.setattr(rh_mcp_client, "get_equity_positions", lambda account_number: POSITIONS)
    monkeypatch.setattr(rh_mcp_client, "get_equity_quotes", lambda symbols: QUOTES)
    monkeypatch.setattr("src.adapters.robinhood_live.get_watchlist", lambda: [])


class TestLiveAdapter:
    def test_defaults_to_the_default_account(self, live):
        assert RobinhoodLiveAdapter().resolve_account()["account_number"] == "999"

    def test_an_explicit_account_is_honoured(self, live):
        assert RobinhoodLiveAdapter("111").resolve_account()["account_number"] == "111"

    def test_an_unknown_account_is_refused_not_silently_swapped(self, live):
        with pytest.raises(RuntimeError, match="not among"):
            RobinhoodLiveAdapter("nope").resolve_account()

    def test_values_and_pl_are_computed_from_shares_and_price(self, live):
        snapshot = RobinhoodLiveAdapter().get_snapshot()
        voo = next(h for h in snapshot["holdings"] if h["ticker"] == "VOO")
        assert voo["market_value"] == pytest.approx(1420.0)
        assert voo["unrealized_pl"] == pytest.approx(20.0)
        assert voo["unrealized_pl_pct"] == pytest.approx(20.0 / 1400.0)

    def test_holdings_are_sorted_by_value(self, live):
        snapshot = RobinhoodLiveAdapter().get_snapshot()
        assert [h["ticker"] for h in snapshot["holdings"]] == ["VOO", "NVDA"]

    def test_locked_shares_are_surfaced(self, live):
        """A position held for grants isn't freely disposable — don't hide that."""
        snapshot = RobinhoodLiveAdapter().get_snapshot()
        nvda = next(h for h in snapshot["holdings"] if h["ticker"] == "NVDA")
        assert nvda["shares_held_for_grants"] == pytest.approx(0.5)
        assert nvda["shares_available"] == pytest.approx(0.0)

    def test_a_missing_cost_basis_yields_none_not_zero(self, live, monkeypatch):
        monkeypatch.setattr(
            rh_mcp_client,
            "get_equity_positions",
            lambda account_number: [{"symbol": "VOO", "quantity": "1.0"}],
        )
        holding = RobinhoodLiveAdapter().get_snapshot()["holdings"][0]
        assert holding["cost_basis_per_share"] is None
        assert holding["unrealized_pl"] is None

    def test_snapshot_satisfies_the_portfolio_adapter_shape(self, live):
        """Downstream code must not care which adapter produced the snapshot."""
        snapshot = RobinhoodLiveAdapter().get_snapshot()
        for field in ("cash", "holdings", "watchlist", "total_portfolio_value", "as_of"):
            assert field in snapshot
        assert all(h["weight"] is not None for h in snapshot["holdings"])


class TestOAuthState:
    def test_tokens_are_written_with_owner_only_permissions(self, tmp_path, monkeypatch):
        """A refresh token on a shared machine must not be world-readable."""
        path = tmp_path / ".rh_token.json"
        monkeypatch.setattr(rh_oauth, "TOKEN_PATH", path)
        rh_oauth._write_state({"refresh_token": "secret"})
        assert oct(path.stat().st_mode)[-3:] == "600"

    def test_status_never_leaks_a_token_value(self, tmp_path, monkeypatch):
        path = tmp_path / ".rh_token.json"
        monkeypatch.setattr(rh_oauth, "TOKEN_PATH", path)
        rh_oauth._write_state(
            {"access_token": "SECRET", "refresh_token": "ALSO_SECRET", "expires_at": time.time() + 60}
        )
        status = rh_oauth.connection_status()
        assert status["connected"] is True
        assert "SECRET" not in json.dumps(status)

    def test_a_mismatched_callback_state_is_rejected(self, tmp_path, monkeypatch):
        """The CSRF state is the only thing standing between a forged callback and a token."""
        path = tmp_path / ".rh_token.json"
        monkeypatch.setattr(rh_oauth, "TOKEN_PATH", path)
        rh_oauth._write_state({"oauth_state": "expected", "client_id": "abc"})
        with pytest.raises(rh_oauth.RobinhoodAuthError, match="did not match"):
            rh_oauth.complete_authorization("code", "forged")

    def test_an_unstarted_flow_cannot_be_completed(self, tmp_path, monkeypatch):
        monkeypatch.setattr(rh_oauth, "TOKEN_PATH", tmp_path / "none.json")
        with pytest.raises(rh_oauth.RobinhoodAuthError, match="No authorization is in progress"):
            rh_oauth.complete_authorization("code", "whatever")

    def test_expiry_triggers_a_refresh(self, tmp_path, monkeypatch):
        path = tmp_path / ".rh_token.json"
        monkeypatch.setattr(rh_oauth, "TOKEN_PATH", path)
        rh_oauth._write_state(
            {"access_token": "old", "refresh_token": "r", "client_id": "c", "expires_at": time.time() - 1}
        )
        monkeypatch.setattr(
            rh_oauth, "get_metadata", lambda: {"token_endpoint": "https://example.test/token"}
        )
        monkeypatch.setattr(
            rh_oauth, "_post_json", lambda *a, **k: {"access_token": "new", "expires_in": 3600}
        )
        assert rh_oauth.get_access_token() == "new"

    def test_no_token_gives_an_actionable_message(self, tmp_path, monkeypatch):
        monkeypatch.setattr(rh_oauth, "TOKEN_PATH", tmp_path / "none.json")
        with pytest.raises(rh_oauth.RobinhoodAuthError, match="Connect"):
            rh_oauth.get_access_token()
