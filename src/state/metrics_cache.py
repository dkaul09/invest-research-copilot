"""Disk-backed cache for computed metrics.

Keyed on ``(ticker, fiscal_year, metric_set_version)``. The version
component means a change to ``metrics_engine`` (a new ratio, a fixed bug)
invalidates stale entries automatically instead of silently serving numbers
computed under the old logic — bump ``METRIC_SET_VERSION`` whenever the
engine's output shape or formulas change.

This is a cache for a pure function, not a source of truth: deleting the
cache file changes nothing except how much gets recomputed next time.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

# Bump this whenever metrics_engine.compute_ratios changes its formulas or
# output shape, so old cached values are never served under new semantics.
METRIC_SET_VERSION = 1

DEFAULT_CACHE_PATH = Path(__file__).resolve().parents[2] / "data" / "sessions" / "metrics_cache.json"


class MetricsCache:
    def __init__(self, cache_path: Path = DEFAULT_CACHE_PATH) -> None:
        self._path = cache_path
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._data: dict[str, Any] = self._load()

    def _load(self) -> dict[str, Any]:
        if not self._path.exists():
            return {}
        with open(self._path, "r", encoding="utf-8") as f:
            return json.load(f)

    def _save(self) -> None:
        with open(self._path, "w", encoding="utf-8") as f:
            json.dump(self._data, f, indent=2)

    @staticmethod
    def _key(ticker: str, fiscal_year: int | None) -> str:
        return f"{ticker.upper()}:{fiscal_year}:{METRIC_SET_VERSION}"

    def get(self, ticker: str, fiscal_year: int | None) -> dict[str, Any] | None:
        return self._data.get(self._key(ticker, fiscal_year))

    def set(self, ticker: str, fiscal_year: int | None, value: dict[str, Any]) -> None:
        self._data[self._key(ticker, fiscal_year)] = value
        self._save()


_default_cache: MetricsCache | None = None


def get_default_cache() -> MetricsCache:
    global _default_cache
    if _default_cache is None:
        _default_cache = MetricsCache()
    return _default_cache


def compute_ratios_cached(ticker: str, fiscal_year: int | None, fundamentals: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    """Return (result, cache_hit) for compute_ratios, using the disk cache."""
    from src.tools.metrics_engine import compute_ratios  # local import avoids a cycle

    cache = get_default_cache()
    cached = cache.get(ticker, fiscal_year)
    if cached is not None:
        return cached, True

    result = compute_ratios(fundamentals)
    cache.set(ticker, fiscal_year, result)
    return result, False
