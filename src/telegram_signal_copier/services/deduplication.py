"""Signal deduplication guard with JSON persistence.

Prevents the same trade signal from being acted on twice — for example if a
signal is forwarded by multiple channels, or the same image+text arrives twice
due to a service restart.

A fingerprint is generated from the normalised symbol, direction, entry price,
and stop-loss.  If that fingerprint was already recorded within the configured
window (default 4 hours), the signal is rejected as a duplicate.

State is persisted to a JSON file so the window survives restarts.
"""
from __future__ import annotations

import hashlib
import json
import logging
import time
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


class DeduplicationGuard:
    """Fingerprint-based duplicate signal detector.

    Usage::

        guard = DeduplicationGuard(
            store_file=config.bridge_root / "dedup_state.json",
            window_hours=4.0,
        )

        # Before executing a trade:
        if guard.is_duplicate(symbol, direction, entry, sl):
            logger.warning("Duplicate signal — skipping")
            return

        # After successfully executing:
        guard.record(symbol, direction, entry, sl)
    """

    def __init__(
        self,
        store_file: str | Path,
        window_hours: float = 4.0,
    ) -> None:
        self._store_file = Path(store_file)
        self._window_seconds = window_hours * 3600.0
        self._seen: dict[str, float] = {}   # fingerprint → first-seen Unix timestamp
        self._load()

    # ── Public API ────────────────────────────────────────────────────────

    def is_duplicate(
        self,
        symbol: str,
        direction: str,
        entry: Optional[float],
        sl: Optional[float],
    ) -> bool:
        """Return True if this signal fingerprint was seen within the window."""
        fp = self._fingerprint(symbol, direction, entry, sl)
        if fp in self._seen:
            age = time.time() - self._seen[fp]
            if age < self._window_seconds:
                logger.info(
                    "[DEDUP] Duplicate detected: symbol=%s dir=%s entry=%s sl=%s age=%.0fs",
                    symbol, direction, entry, sl, age,
                )
                return True
            # Expired — remove it so it can be re-recorded
            del self._seen[fp]
        return False

    def record(
        self,
        symbol: str,
        direction: str,
        entry: Optional[float],
        sl: Optional[float],
    ) -> None:
        """Record a signal fingerprint as acted-upon."""
        fp = self._fingerprint(symbol, direction, entry, sl)
        self._seen[fp] = time.time()
        self._evict_old()
        self._save()
        logger.debug("[DEDUP] Recorded fingerprint for symbol=%s dir=%s", symbol, direction)

    # ── Fingerprint generation ────────────────────────────────────────────

    @staticmethod
    def _fingerprint(
        symbol: str,
        direction: str,
        entry: Optional[float],
        sl: Optional[float],
    ) -> str:
        """16-char hex fingerprint stable across restarts."""
        key = json.dumps(
            {
                "s": symbol.upper().strip(),
                "d": direction.lower().strip(),
                "e": round(entry, 4) if entry is not None else None,
                "sl": round(sl, 4) if sl is not None else None,
            },
            sort_keys=True,
        )
        return hashlib.sha256(key.encode()).hexdigest()[:16]

    # ── Persistence ───────────────────────────────────────────────────────

    def _evict_old(self) -> None:
        """Remove expired fingerprints from the in-memory store."""
        cutoff = time.time() - self._window_seconds
        self._seen = {k: v for k, v in self._seen.items() if v >= cutoff}

    def _save(self) -> None:
        tmp = self._store_file.with_suffix(self._store_file.suffix + ".tmp")
        try:
            tmp.write_text(json.dumps(self._seen), encoding="utf-8")
            tmp.replace(self._store_file)
        except Exception:
            logger.exception("[DEDUP] Failed to save state to %s", self._store_file)
            try:
                tmp.unlink(missing_ok=True)
            except Exception:
                pass

    def _load(self) -> None:
        if not self._store_file.exists():
            return
        try:
            raw = json.loads(self._store_file.read_text(encoding="utf-8"))
            self._seen = {k: float(v) for k, v in raw.items()}
            self._evict_old()
            logger.info(
                "[DEDUP] Loaded %d fingerprints from %s", len(self._seen), self._store_file
            )
        except Exception:
            logger.exception("[DEDUP] Failed to load state — starting empty")
            self._seen = {}
