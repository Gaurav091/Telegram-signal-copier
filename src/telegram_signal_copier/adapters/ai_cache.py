"""AI response cache: in-memory LRU-style + optional shelve persistence."""
from __future__ import annotations

import logging
import threading
import time
from typing import Any

logger = logging.getLogger(__name__)


class AIResponseCache:
    """Thread-safe response cache with optional shelve persistence.

    Args:
        ttl_seconds: How long cached entries stay valid.
        persistent_db: An open shelve database for cross-restart caching.
            Pass ``None`` to disable persistence.
    """

    def __init__(self, ttl_seconds: int = 300, persistent_db: Any = None) -> None:
        self._ttl = ttl_seconds
        self._store: dict[str, tuple[float, dict[str, Any]]] = {}
        self._lock = threading.Lock()
        self._persistent_db = persistent_db

    # ------------------------------------------------------------------
    def get(self, key: str) -> dict[str, Any] | None:
        """Return a cached value if present and still fresh, else ``None``."""
        now = time.time()
        # Check persistent store first so cross-restart hits are counted.
        if self._persistent_db is not None:
            try:
                if key in self._persistent_db:
                    ts, value = self._persistent_db[key]
                    if (now - ts) < self._ttl:
                        return value
            except Exception:
                logger.debug("Persistent cache read failed for key=%s", key, exc_info=True)

        with self._lock:
            entry = self._store.get(key)
            if entry and (now - entry[0]) < self._ttl:
                return entry[1]
        return None

    def put(self, key: str, value: dict[str, Any]) -> None:
        """Store *value* under *key* with the current timestamp."""
        now = time.time()
        with self._lock:
            self._store[key] = (now, value)
        if self._persistent_db is not None:
            try:
                self._persistent_db[key] = (now, value)
                try:
                    self._persistent_db.sync()
                except Exception:
                    logger.debug("Persistent cache sync failed", exc_info=True)
            except Exception:
                logger.debug("Persistent cache write failed for key=%s", key, exc_info=True)

    def close(self) -> None:
        """Close the persistent database if one was provided."""
        if self._persistent_db is not None:
            try:
                self._persistent_db.close()
            except Exception:
                logger.debug("Persistent cache close failed", exc_info=True)
            finally:
                self._persistent_db = None
