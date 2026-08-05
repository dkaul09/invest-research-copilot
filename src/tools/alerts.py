"""Personal price-watch conditions.

Like the watchlist, this is deliberately writable: a condition you want to be
told about is a personal to-do, not account data. Nothing here reaches a
brokerage, and nothing here acts — this module only records what you asked to
be notified about.

Storing conditions now, ahead of the watcher that will evaluate them, means
real conditions accumulate from day one instead of being invented later. Until
that watcher exists, every write says plainly that delivery is not yet wired
up, so a saved condition is never mistaken for an active alarm.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ALERTS_PATH = Path(__file__).resolve().parents[2] / "data" / "portfolio" / "alerts.json"

VALID_DIRECTIONS = {"down", "up"}

# What the move is measured against. "view_price" reaches into the research
# ledger for the price a view was formed at, which is what makes an alert about
# a thesis rather than about noise.
VALID_BASELINES = {"prev_close", "7d", "30d", "view_price"}

PENDING_DELIVERY_NOTE = (
    "Condition saved. Delivery is not wired up yet — the watcher that checks "
    "prices ships separately, so nothing will notify you of this yet."
)


def _load() -> list[dict[str, Any]]:
    if not ALERTS_PATH.exists():
        return []
    try:
        data = json.loads(ALERTS_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        # A hand-edited file that no longer parses should not take the tool
        # down; treat it as empty and let the next write rebuild it.
        return []
    return data if isinstance(data, list) else []


def _save(alerts: list[dict[str, Any]]) -> None:
    ALERTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    ALERTS_PATH.write_text(json.dumps(alerts, indent=2) + "\n", encoding="utf-8")


def add_price_alert(
    ticker: str,
    direction: str,
    pct: float,
    baseline: str = "prev_close",
) -> dict[str, Any]:
    """Record a price condition to be notified about later."""
    if direction not in VALID_DIRECTIONS:
        raise ValueError(f"direction must be one of {sorted(VALID_DIRECTIONS)}")
    if baseline not in VALID_BASELINES:
        raise ValueError(f"baseline must be one of {sorted(VALID_BASELINES)}")
    if pct <= 0:
        raise ValueError("pct must be greater than zero")
    if not ticker.strip():
        raise ValueError("ticker is required")

    alert = {
        "id": uuid.uuid4().hex[:6],
        "ticker": ticker.strip().upper(),
        "direction": direction,
        "pct": float(pct),
        "baseline": baseline,
        "enabled": True,
        "created_at": datetime.now(timezone.utc)
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z"),
        "last_fired_at": None,
    }
    alerts = _load()
    alerts.append(alert)
    _save(alerts)
    return {"alert": alert, "note": PENDING_DELIVERY_NOTE}


def list_price_alerts() -> dict[str, Any]:
    """The user's saved price-watch conditions."""
    return {"alerts": _load()}


def remove_price_alert(alert_id: str) -> dict[str, Any]:
    """Delete a saved condition by id."""
    alerts = _load()
    remaining = [a for a in alerts if a.get("id") != alert_id]
    if len(remaining) == len(alerts):
        return {"removed": False, "reason": f"No condition with id {alert_id}."}
    _save(remaining)
    return {"removed": True, "id": alert_id}
