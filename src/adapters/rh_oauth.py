"""OAuth 2.1 client for Robinhood's agent MCP endpoint.

The dashboard needs its own connection to Robinhood — it cannot borrow the
one a Claude Code session holds, because that token lives in the CLI's
credential store and is scoped to that process. Fortunately the endpoint
advertises a standard OAuth 2.1 setup, verified against its published
metadata:

- dynamic client registration, so no client secret is ever issued or stored
- authorization code + PKCE (S256), so no password reaches this backend
- refresh tokens, so the user authorizes once rather than every session
- a public client (``token_endpoint_auth_methods_supported: ["none"]``)

**The honest caveat.** Robinhood publishes exactly one scope, ``internal``.
There is no read-only scope to request, so the token this module obtains is
a full-power token. ``adapters/base.py`` asks that credentials be scoped
read-only *at the provider*, and that is not achievable here. The
compensating controls live in ``rh_mcp_client.py``, which refuses to call
any tool outside a read-only allowlist — see that module for why this is
enforced there rather than trusted here.

Tokens are written to ``data/portfolio/.rh_token.json`` (gitignored) with
owner-only permissions. They are never logged, never returned by an API
route, and never committed.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

RESOURCE = "https://agent.robinhood.com/mcp/trading"
PROTECTED_RESOURCE_METADATA = (
    "https://agent.robinhood.com/.well-known/oauth-protected-resource/mcp/trading"
)
AUTH_SERVER_METADATA = "https://agent.robinhood.com/.well-known/oauth-authorization-server"

TOKEN_PATH = Path(__file__).resolve().parents[2] / "data" / "portfolio" / ".rh_token.json"

# Refresh a little before actual expiry so a dashboard load never races it.
_EXPIRY_SKEW_SECONDS = 60


class RobinhoodAuthError(Exception):
    """Raised when the connection isn't authorized or a token exchange fails."""


def _post_json(url: str, payload: dict[str, Any], form: bool = False) -> dict[str, Any]:
    if form:
        body = urllib.parse.urlencode(payload).encode()
        headers = {"Content-Type": "application/x-www-form-urlencoded"}
    else:
        body = json.dumps(payload).encode()
        headers = {"Content-Type": "application/json"}
    request = urllib.request.Request(url, data=body, headers={**headers, "Accept": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.loads(response.read())
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:400]
        raise RobinhoodAuthError(f"{url} returned HTTP {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise RobinhoodAuthError(f"Could not reach {url}: {exc}") from exc


def _get_json(url: str) -> dict[str, Any]:
    request = urllib.request.Request(url, headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.loads(response.read())
    except (urllib.error.HTTPError, urllib.error.URLError) as exc:
        raise RobinhoodAuthError(f"Could not read {url}: {exc}") from exc


def get_metadata() -> dict[str, Any]:
    """Fetch the authorization server's published OAuth metadata."""
    return _get_json(AUTH_SERVER_METADATA)


def _read_state() -> dict[str, Any]:
    if not TOKEN_PATH.exists():
        return {}
    try:
        with open(TOKEN_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def _write_state(state: dict[str, Any]) -> None:
    TOKEN_PATH.parent.mkdir(parents=True, exist_ok=True)
    # Write private, then move into place: an intermediate world-readable
    # file would be a window where a refresh token sat exposed on disk.
    tmp_path = TOKEN_PATH.with_suffix(".tmp")
    fd = os.open(tmp_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(state, f)
    os.replace(tmp_path, TOKEN_PATH)
    os.chmod(TOKEN_PATH, 0o600)


def register_client() -> dict[str, Any]:
    """Register this dashboard as an OAuth client, reusing a prior registration."""
    state = _read_state()
    if state.get("client_id"):
        return state

    metadata = get_metadata()
    registration_endpoint = metadata.get("registration_endpoint")
    if not registration_endpoint:
        raise RobinhoodAuthError("Robinhood's OAuth metadata advertises no registration endpoint.")

    registration = _post_json(
        registration_endpoint,
        {
            "client_name": "Investment Research Copilot (dashboard)",
            "redirect_uris": [state.get("redirect_uri") or _default_redirect_uri()],
            "grant_types": ["authorization_code", "refresh_token"],
            "response_types": ["code"],
            "token_endpoint_auth_method": "none",
        },
    )
    state["client_id"] = registration["client_id"]
    _write_state(state)
    return state


def _default_redirect_uri() -> str:
    port = os.environ.get("COPILOT_PORT", "8000")
    return f"http://localhost:{port}/api/live/callback"


def build_authorization_url(redirect_uri: str | None = None) -> str:
    """Start the flow: return the URL the user opens to authorize the dashboard.

    The PKCE verifier is stashed alongside the client registration so the
    callback can complete the exchange. It is single-use.
    """
    redirect_uri = redirect_uri or _default_redirect_uri()
    state = _read_state()
    state["redirect_uri"] = redirect_uri
    _write_state(state)

    state = register_client()
    metadata = get_metadata()

    verifier = base64.urlsafe_b64encode(secrets.token_bytes(64)).decode().rstrip("=")
    challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
    )
    csrf_state = secrets.token_urlsafe(24)

    state["pkce_verifier"] = verifier
    state["oauth_state"] = csrf_state
    state["redirect_uri"] = redirect_uri
    _write_state(state)

    query = urllib.parse.urlencode(
        {
            "response_type": "code",
            "client_id": state["client_id"],
            "redirect_uri": redirect_uri,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "state": csrf_state,
            "scope": " ".join(metadata.get("scopes_supported") or ["internal"]),
            "resource": RESOURCE,
        }
    )
    return f"{metadata['authorization_endpoint']}?{query}"


def complete_authorization(code: str, returned_state: str) -> None:
    """Exchange an authorization code for tokens, verifying the CSRF state."""
    state = _read_state()
    expected = state.get("oauth_state")
    if not expected:
        raise RobinhoodAuthError("No authorization is in progress — start the connection again.")
    # Constant-time compare: this value is the only thing standing between a
    # forged callback and a token exchange.
    if not secrets.compare_digest(str(returned_state), str(expected)):
        raise RobinhoodAuthError("Authorization state did not match — the callback was not trusted.")

    metadata = get_metadata()
    tokens = _post_json(
        metadata["token_endpoint"],
        {
            "grant_type": "authorization_code",
            "code": code,
            "client_id": state["client_id"],
            "redirect_uri": state["redirect_uri"],
            "code_verifier": state["pkce_verifier"],
            "resource": RESOURCE,
        },
        form=True,
    )
    _store_tokens(state, tokens)


def _store_tokens(state: dict[str, Any], tokens: dict[str, Any]) -> None:
    if "access_token" not in tokens:
        raise RobinhoodAuthError(f"Token response contained no access token: {sorted(tokens)}")
    state["access_token"] = tokens["access_token"]
    if tokens.get("refresh_token"):
        state["refresh_token"] = tokens["refresh_token"]
    expires_in = tokens.get("expires_in")
    state["expires_at"] = time.time() + float(expires_in) if expires_in else None
    # One-time values: clearing them means a replayed callback can't re-exchange.
    state.pop("pkce_verifier", None)
    state.pop("oauth_state", None)
    _write_state(state)


def _refresh(state: dict[str, Any]) -> str:
    refresh_token = state.get("refresh_token")
    if not refresh_token:
        raise RobinhoodAuthError("Access token expired and no refresh token is stored — reconnect.")
    metadata = get_metadata()
    tokens = _post_json(
        metadata["token_endpoint"],
        {
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "client_id": state["client_id"],
            "resource": RESOURCE,
        },
        form=True,
    )
    _store_tokens(state, tokens)
    return state["access_token"]


def get_access_token() -> str:
    """Return a valid access token, refreshing it if it's expired or near expiry."""
    state = _read_state()
    token = state.get("access_token")
    if not token:
        raise RobinhoodAuthError(
            "The dashboard isn't connected to Robinhood yet. Use the Connect button to authorize it."
        )

    expires_at = state.get("expires_at")
    if expires_at and time.time() >= float(expires_at) - _EXPIRY_SKEW_SECONDS:
        return _refresh(state)
    return token


def connection_status() -> dict[str, Any]:
    """Report whether the dashboard is connected. Never returns a token value."""
    state = _read_state()
    expires_at = state.get("expires_at")
    return {
        "connected": bool(state.get("access_token")),
        "has_refresh_token": bool(state.get("refresh_token")),
        "expires_at": expires_at,
        "expired": bool(expires_at and time.time() >= float(expires_at)),
    }


def disconnect() -> None:
    """Forget all stored credentials."""
    if TOKEN_PATH.exists():
        TOKEN_PATH.unlink()
