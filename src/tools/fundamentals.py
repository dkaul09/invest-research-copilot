"""Loads the ``fundamentals`` block from each filing's YAML front matter.

This is the single source of raw financial inputs used by both
``metrics_engine`` (for ratio computation) and ``peer_compare`` (for
building comparison tables). Keeping one loader means a number only ever
enters the system from one place, which is what makes it possible to trace
every figure in a research note back to a filing.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

DEFAULT_FILINGS_DIR = Path(__file__).resolve().parents[2] / "data" / "filings"


def load_all_fundamentals(filings_dir: Path = DEFAULT_FILINGS_DIR) -> dict[str, dict[str, Any]]:
    """Return {ticker: fundamentals_dict} for every filing in the corpus."""
    result: dict[str, dict[str, Any]] = {}
    for path in sorted(filings_dir.glob("*.md")):
        raw = path.read_text(encoding="utf-8")
        _, front_matter_raw, _ = raw.split("---", 2)
        meta = yaml.safe_load(front_matter_raw)
        ticker = meta["ticker"]
        result[ticker] = {
            "company": meta.get("company", ticker),
            "fiscal_year": meta.get("fiscal_year"),
            **meta.get("fundamentals", {}),
        }
    return result


def get_fundamentals(ticker: str, filings_dir: Path = DEFAULT_FILINGS_DIR) -> dict[str, Any] | None:
    return load_all_fundamentals(filings_dir).get(ticker.upper())
