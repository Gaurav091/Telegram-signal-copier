"""
MessageClusterAgent — Context-aware multi-message signal assembler.

Parsing logic (regex patterns, ClusterSignal, parse_cluster, auto_derive_sl)
lives in cluster_parser.py. This module contains only the stateful agent.

Configuration via env vars
--------------------------
CLUSTER_WINDOW_SECONDS      Rolling window to accumulate follow-up messages (default 120)
CLUSTER_AUTO_SL_PIPS        Pips added/subtracted beyond entry range for auto SL (default 20)
CLUSTER_ENABLED             "1"/"true" to enable (default "1")
"""
from __future__ import annotations

import asyncio
import logging
import os
import time
from collections import defaultdict
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from telegram_signal_copier.models import TelegramSignalMessage
from telegram_signal_copier.services.cluster_parser import (
    ClusterSignal,
    auto_derive_sl,
    parse_cluster,
)

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────────────────────
# Internal state
# ──────────────────────────────────────────────────────────────────────────────

@dataclass
class _SourceCluster:
    messages: list[TelegramSignalMessage] = field(default_factory=list)
    last_updated: float = field(default_factory=time.monotonic)


class MessageClusterAgent:
    """
    Sits between the ``MessageBuffer`` flush and the ``CopierPipeline``.

    When a flushed message arrives:
    1. Append to the per-source cluster.
    2. Re-parse the whole cluster context.
    3. Emit a synthetic ``TelegramSignalMessage`` enriched with cluster-derived levels.
    4. Expire stale clusters after ``window_seconds``.

    Usage::

        agent = MessageClusterAgent(allowed_symbols=config.merged_allowed_symbols)
        async def on_message_with_cluster(msg):
            await agent.process(msg, original_on_message)
    """

    def __init__(
        self,
        allowed_symbols: list[str] | None = None,
        window_seconds: float | None = None,
        auto_sl_pips: float | None = None,
        enabled: bool = True,
    ) -> None:
        self.enabled = enabled and os.getenv("CLUSTER_ENABLED", "1").lower() in ("1", "true", "yes")
        self.window_seconds = window_seconds or float(os.getenv("CLUSTER_WINDOW_SECONDS", "120"))
        self.auto_sl_pips = auto_sl_pips or float(os.getenv("CLUSTER_AUTO_SL_PIPS", "20"))
        self.allowed_symbols = allowed_symbols or []
        self._clusters: dict[str, _SourceCluster] = defaultdict(_SourceCluster)
        self._lock = asyncio.Lock()

    async def process(
        self,
        message: TelegramSignalMessage,
        callback: Callable[[TelegramSignalMessage], Awaitable[None]],
    ) -> None:
        if not self.enabled:
            await callback(message)
            return

        async with self._lock:
            self._expire_stale()
            key = message.source_group
            cluster = self._clusters[key]
            cluster.messages.append(message)
            cluster.last_updated = time.monotonic()

            texts = [m.raw_text for m in cluster.messages if m.raw_text]
            sig = parse_cluster(texts, self.allowed_symbols)
            sig = auto_derive_sl(sig, self.auto_sl_pips)

            logger.info(
                "[CLUSTER] source=%s msgs=%d symbol=%s side=%s entry=%s SL=%s TP=%s conf=%.2f",
                key,
                len(cluster.messages),
                sig.symbol,
                sig.side,
                sig.entry_price,
                sig.stop_loss,
                sig.take_profits,
                sig.confidence,
            )

            enriched = self._enrich_message(message, sig)

        await callback(enriched)

    def _enrich_message(
        self, original: TelegramSignalMessage, sig: ClusterSignal
    ) -> TelegramSignalMessage:
        """Inject cluster-derived levels into raw_text as a structured header."""
        if not any([sig.symbol, sig.side, sig.entry_price, sig.stop_loss, sig.take_profits]):
            return original

        lines: list[str] = ["[CLUSTER CONTEXT]"]
        if sig.symbol:
            lines.append(f"Symbol: {sig.symbol}")
        if sig.side:
            lines.append(f"Side: {sig.side}")
        if sig.order_type and sig.order_type != "MARKET":
            lines.append(f"Order: {sig.order_type}")
        if sig.entry_range_low is not None and sig.entry_range_high is not None:
            lines.append(f"Entry range: {sig.entry_range_low}-{sig.entry_range_high}")
        if sig.entry_price is not None:
            lines.append(f"Entry: {sig.entry_price}")
        if sig.stop_loss is not None:
            lines.append(f"SL: {sig.stop_loss}")
        if sig.take_profits:
            lines.append("TP: " + " ".join(str(tp) for tp in sig.take_profits))
        for note in sig.notes:
            lines.append(f"# {note}")
        lines.append("[/CLUSTER CONTEXT]")

        cluster_header = "\n".join(lines)
        new_text = cluster_header + "\n---\n" + (original.raw_text or "")

        return TelegramSignalMessage(
            source_group=original.source_group,
            message_id=original.message_id,
            raw_text=new_text,
            image_path=original.image_path,
            sender=original.sender,
            received_at=original.received_at,
            all_image_paths=original.all_image_paths,
            grouped_count=original.grouped_count,
        )

    def _expire_stale(self) -> None:
        now = time.monotonic()
        stale = [k for k, v in self._clusters.items()
                 if now - v.last_updated > self.window_seconds]
        for k in stale:
            logger.debug("[CLUSTER] Expired cluster for source=%s", k)
            del self._clusters[k]

    def clear_source(self, source: str) -> None:
        self._clusters.pop(source, None)
