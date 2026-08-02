"""Structured per-tool-call tracing.

Wrapping a tool function in ``@traced`` writes one JSON line per call to
``logs/traces/<date>.jsonl`` with the tool name, a digest of its arguments,
wall-clock latency, and result size. Stdlib only — no vendor tracing SDK —
so this works offline and needs no configuration. This is the artifact you'd
point to when asked "how do you debug this agent," not a promise that it
replaces a real observability stack for a production system.
"""

from __future__ import annotations

import functools
import hashlib
import json
import time
from pathlib import Path
from typing import Any, Callable

DEFAULT_TRACE_DIR = Path(__file__).resolve().parents[2] / "logs" / "traces"


def _args_digest(args: tuple, kwargs: dict) -> str:
    try:
        payload = json.dumps({"args": args, "kwargs": kwargs}, sort_keys=True, default=str)
    except TypeError:
        payload = repr((args, kwargs))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:12]


def _result_size(result: Any) -> int:
    try:
        return len(json.dumps(result, default=str))
    except TypeError:
        return len(repr(result))


def _write_trace(record: dict[str, Any], trace_dir: Path) -> None:
    trace_dir.mkdir(parents=True, exist_ok=True)
    date_str = time.strftime("%Y-%m-%d")
    path = trace_dir / f"{date_str}.jsonl"
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record) + "\n")


def traced(tool_name: str | None = None, trace_dir: Path = DEFAULT_TRACE_DIR) -> Callable:
    """Decorator: log one JSONL trace line per call of the wrapped function."""

    def decorator(func: Callable) -> Callable:
        name = tool_name or func.__name__

        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            start = time.monotonic()
            error: str | None = None
            result: Any = None
            try:
                result = func(*args, **kwargs)
                return result
            except Exception as exc:  # re-raised after logging
                error = repr(exc)
                raise
            finally:
                elapsed_ms = round((time.monotonic() - start) * 1000, 2)
                cache_hit = None
                if isinstance(result, tuple) and len(result) == 2 and isinstance(result[1], bool):
                    cache_hit = result[1]
                _write_trace(
                    {
                        "tool": name,
                        "args_digest": _args_digest(args, kwargs),
                        "elapsed_ms": elapsed_ms,
                        "result_size": _result_size(result) if error is None else None,
                        "cache_hit": cache_hit,
                        "error": error,
                    },
                    trace_dir,
                )

        return wrapper

    return decorator
