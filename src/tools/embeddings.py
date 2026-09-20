"""Dense embeddings for filing retrieval, with a disk cache and a hard fallback.

BM25 alone has a failure this corpus demonstrates: AAPL's "Risk Factors:
Supply Chain Concentration" section never writes the words *supply*,
*chain*, or *concentration* in its body. It says "suppliers", "contract
manufacturers", "concentrated in China". A lexical query for "supply chain
concentration risk" scored that chunk exactly 0.0 and ranked a margin
discussion first. No amount of BM25 tuning fixes a term that isn't there.

Embeddings fix it, so retrieval runs both and fuses the rankings (see
``hybrid_search.py``). This module is the embedding half.

Three properties matter more than raw quality here:

1. **It must work with no configuration.** A retrieval path that silently
   degrades because nobody exported an API key is worse than no retrieval
   path, because the note still gets written and nothing says the evidence
   was found the weak way. The default backend is therefore a local model
   with no key, no network at query time, and no GPU.
2. **It must degrade honestly.** If no backend can load, `get_backend()`
   returns None, hybrid search falls back to pure BM25, and the caller can
   see that happened via `backend_id()`. It never fakes a vector.
3. **It must not re-embed the same text twice.** Filing chunks are stable;
   a 10-K fetched today has the same windows tomorrow. Vectors are cached
   to disk keyed by a hash of the exact text plus the backend id, so a
   model or dimension change can never silently read stale vectors.
"""

from __future__ import annotations

import hashlib
import os
import threading
from pathlib import Path
from typing import Any, Protocol

import numpy as np

CACHE_DIR = Path(__file__).resolve().parents[2] / "data" / "embedding_cache"

# Local, no API key, pure-numpy inference. Distilled for retrieval
# specifically, which is what this corpus needs.
DEFAULT_LOCAL_MODEL = "minishlab/potion-retrieval-32M"

# Voyage publishes a finance-tuned embedding model, and this corpus is
# nothing but SEC filings — if a key is present it is the better choice.
DEFAULT_VOYAGE_MODEL = "voyage-finance-2"


class EmbeddingBackend(Protocol):
    id: str

    def encode(self, texts: list[str]) -> np.ndarray:
        """Return an L2-normalized (n, dim) float32 array."""
        ...


def _normalize(matrix: np.ndarray) -> np.ndarray:
    matrix = np.asarray(matrix, dtype=np.float32)
    if matrix.ndim == 1:
        matrix = matrix.reshape(1, -1)
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    # A zero vector would divide to NaN and then poison every downstream
    # cosine score, so clamp instead.
    norms[norms == 0] = 1.0
    return matrix / norms


class Model2VecBackend:
    """Local static embeddings. No key, no network at query time, no torch."""

    def __init__(self, model_name: str = DEFAULT_LOCAL_MODEL) -> None:
        from model2vec import StaticModel

        self._model = StaticModel.from_pretrained(model_name)
        self.id = f"model2vec:{model_name}"

    def encode(self, texts: list[str]) -> np.ndarray:
        return _normalize(self._model.encode(texts))


class VoyageBackend:
    """Voyage AI's finance-tuned embeddings. Opt-in via VOYAGE_API_KEY."""

    def __init__(self, model_name: str = DEFAULT_VOYAGE_MODEL) -> None:
        import voyageai

        self._client = voyageai.Client()
        self._model = model_name
        self.id = f"voyage:{model_name}"

    def encode(self, texts: list[str]) -> np.ndarray:
        vectors: list[list[float]] = []
        # Voyage caps documents per request; batch rather than fail on a
        # long 10-K, which chunks into hundreds of windows.
        for i in range(0, len(texts), 128):
            batch = texts[i : i + 128]
            vectors.extend(self._client.embed(batch, model=self._model).embeddings)
        return _normalize(np.array(vectors, dtype=np.float32))


class _CachedBackend:
    """Wraps a backend with a persistent, content-addressed vector cache.

    Keyed by sha256(text) within a per-backend file, so switching models or
    dimensions can never read another model's vectors back.
    """

    def __init__(self, inner: EmbeddingBackend) -> None:
        self._inner = inner
        self.id = inner.id
        self._lock = threading.Lock()
        safe = self.id.replace("/", "_").replace(":", "_")
        self._path = CACHE_DIR / f"{safe}.npz"
        self._store: dict[str, np.ndarray] = {}
        self._dirty = False
        if self._path.exists():
            try:
                with np.load(self._path) as data:
                    self._store = {k: data[k] for k in data.files}
            except Exception:
                # A truncated or half-written cache is a performance
                # problem, not a correctness one — drop it and re-embed.
                self._store = {}

    @staticmethod
    def _key(text: str) -> str:
        return hashlib.sha256(text.encode("utf-8")).hexdigest()

    def encode(self, texts: list[str]) -> np.ndarray:
        keys = [self._key(t) for t in texts]
        missing = [(k, t) for k, t in zip(keys, texts) if k not in self._store]
        if missing:
            fresh = self._inner.encode([t for _, t in missing])
            for (k, _), vector in zip(missing, fresh):
                self._store[k] = vector
            self._dirty = True
        return np.vstack([self._store[k] for k in keys])

    def flush(self) -> None:
        if not self._dirty:
            return
        with self._lock:
            CACHE_DIR.mkdir(parents=True, exist_ok=True)
            # Write-then-rename so an interrupted flush can't leave a
            # half-written cache where the next process will read it.
            tmp = self._path.with_suffix(".npz.tmp")
            # Write through an open handle: np.savez appends ".npz" to a
            # path that lacks it, which would silently produce a differently
            # named file and make the rename below fail.
            with open(tmp, "wb") as handle:
                np.savez(handle, **self._store)
            tmp.replace(self._path)
            self._dirty = False


_backend: EmbeddingBackend | None = None
_resolved = False
_resolve_lock = threading.Lock()


def _build_backend() -> EmbeddingBackend | None:
    if os.environ.get("IRC_EMBEDDINGS", "").lower() in {"off", "0", "false"}:
        return None

    if os.environ.get("VOYAGE_API_KEY"):
        try:
            return _CachedBackend(VoyageBackend())
        except Exception:
            pass  # fall through to the local model rather than lose retrieval

    try:
        return _CachedBackend(Model2VecBackend())
    except Exception:
        return None


def get_backend() -> EmbeddingBackend | None:
    """The active backend, or None when embeddings are unavailable.

    Resolved once per process. None is a supported state, not an error:
    hybrid search falls back to pure BM25.
    """
    global _backend, _resolved
    if not _resolved:
        with _resolve_lock:
            if not _resolved:
                _backend = _build_backend()
                _resolved = True
    return _backend


def backend_id() -> str:
    backend = get_backend()
    return backend.id if backend else "none"


def embed(texts: list[str]) -> np.ndarray | None:
    """Embed texts, or return None if no backend is available."""
    backend = get_backend()
    if backend is None or not texts:
        return None
    vectors = backend.encode(texts)
    flush = getattr(backend, "flush", None)
    if flush:
        flush()
    return vectors


def reset_backend_for_tests() -> None:
    global _backend, _resolved
    _backend = None
    _resolved = False


def describe() -> dict[str, Any]:
    """Which backend is live — surfaced so a caller can report degradation."""
    return {"backend": backend_id(), "enabled": get_backend() is not None}
