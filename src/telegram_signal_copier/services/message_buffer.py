"""Message grouping buffer.

Collects incoming RawMessage objects from the Telethon listener and groups
them into logical MessageGroup units before releasing them for AI analysis.

Grouping rules (in priority order):
1. Telegram album ID  — messages with the same ``grouped_id`` always belong together.
2. Reply chain        — a reply to a recent message joins its group.
3. Time window        — messages from the same channel within WINDOW_SECONDS are
                         candidates; a lightweight check groups them together.

A group is released (forwarded to the analysis callback) when
``RELEASE_AFTER_SECONDS`` have elapsed since the last message added to it,
OR when a new message clearly starts an unrelated topic.
"""
from __future__ import annotations

import asyncio
import logging
import time
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Awaitable, Callable, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class RawMessage:
    """Wrapper around a Telethon message with extracted metadata."""

    msg_id: int
    channel_id: int
    sender_id: Optional[int]
    timestamp: float                  # Unix epoch (UTC)
    text: Optional[str]               # Message text or caption
    has_image: bool
    image_bytes: Optional[bytes]      # Downloaded image bytes if present
    grouped_id: Optional[int]         # Telegram album grouping ID
    reply_to_msg_id: Optional[int]    # If this is a reply to another message
    image_path: Optional[str] = None  # Local path once image is saved to disk


@dataclass
class MessageGroup:
    """A collection of 1+ raw messages that together form one logical signal."""

    group_id: str
    channel_id: int
    messages: List[RawMessage] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    released: bool = False

    @property
    def combined_text(self) -> str:
        """All text from all messages joined for AI analysis."""
        parts = [m.text for m in self.messages if m.text]
        return "\n".join(parts)

    @property
    def all_images(self) -> List[bytes]:
        """All image bytes from all messages in order."""
        return [m.image_bytes for m in self.messages if m.image_bytes]

    @property
    def all_image_paths(self) -> List[str]:
        """All local image paths from all messages in order."""
        return [m.image_path for m in self.messages if m.image_path]

    @property
    def primary_image_path(self) -> Optional[str]:
        paths = self.all_image_paths
        return paths[0] if paths else None


ReleaseCallback = Callable[[MessageGroup], Awaitable[None]]


class MessageBuffer:
    """Collects incoming messages and groups them into logical signal units.

    Usage::

        async def handle_group(group: MessageGroup) -> None:
            ...

        buffer = MessageBuffer(release_callback=handle_group)

        # Feed messages
        await buffer.ingest(raw_message)

        # Tick loop — call from an asyncio task every second
        asyncio.create_task(_tick_loop(buffer))
    """

    # Configurable class-level defaults (override in constructor)
    WINDOW_SECONDS: float = 45.0
    RELEASE_AFTER_SECONDS: float = 30.0
    MAX_GROUP_SIZE: int = 8
    CONTEXT_HISTORY_SIZE: int = 20

    def __init__(
        self,
        release_callback: ReleaseCallback,
        window_seconds: float | None = None,
        release_after_seconds: float | None = None,
        max_group_size: int | None = None,
        context_history_size: int | None = None,
    ) -> None:
        self._release_callback = release_callback
        self._window_seconds = window_seconds if window_seconds is not None else self.WINDOW_SECONDS
        self._release_after_seconds = (
            release_after_seconds if release_after_seconds is not None else self.RELEASE_AFTER_SECONDS
        )
        self._max_group_size = max_group_size if max_group_size is not None else self.MAX_GROUP_SIZE
        self._context_history_size = (
            context_history_size if context_history_size is not None else self.CONTEXT_HISTORY_SIZE
        )

        self._pending: dict[int, list[MessageGroup]] = defaultdict(list)
        self._history: dict[int, list[MessageGroup]] = defaultdict(list)
        self._lock = asyncio.Lock()

    async def ingest(self, message: RawMessage) -> None:
        """Add a raw message to the appropriate pending group."""
        async with self._lock:
            group = self._find_or_create_group(message)
            group.messages.append(message)
            logger.debug(
                "[BUFFER] Ingested msg_id=%d channel=%d group=%s size=%d",
                message.msg_id,
                message.channel_id,
                group.group_id,
                len(group.messages),
            )

    async def tick(self) -> None:
        """Release groups that are ready.  Call once per second from an asyncio task."""
        now = time.time()
        to_release: list[MessageGroup] = []

        async with self._lock:
            for channel_id, groups in self._pending.items():
                for g in groups:
                    if g.released:
                        continue
                    last_ts = max(m.timestamp for m in g.messages)
                    if (now - last_ts) >= self._release_after_seconds:
                        g.released = True
                        self._history[channel_id].append(g)
                        if len(self._history[channel_id]) > self._context_history_size:
                            self._history[channel_id].pop(0)
                        to_release.append(g)

            # Remove released groups from pending
            for channel_id in list(self._pending):
                self._pending[channel_id] = [
                    g for g in self._pending[channel_id] if not g.released
                ]

        for group in to_release:
            logger.info(
                "[BUFFER] Releasing group=%s channel=%d messages=%d images=%d",
                group.group_id,
                group.channel_id,
                len(group.messages),
                len(group.all_image_paths),
            )
            try:
                await self._release_callback(group)
            except Exception:
                logger.exception("[BUFFER] release_callback raised for group=%s", group.group_id)

    def get_context_history(self, channel_id: int) -> list[MessageGroup]:
        """Return recently released groups for this channel (for AI context injection)."""
        return list(self._history.get(channel_id, []))

    def _find_or_create_group(self, msg: RawMessage) -> MessageGroup:
        channel_groups = self._pending[msg.channel_id]

        # Rule 1: Telegram album grouping
        if msg.grouped_id is not None:
            for g in channel_groups:
                if not g.released and any(m.grouped_id == msg.grouped_id for m in g.messages):
                    return g

        # Rule 2: Reply chain
        if msg.reply_to_msg_id is not None:
            for g in channel_groups:
                if g.released:
                    continue
                if any(m.msg_id == msg.reply_to_msg_id for m in g.messages):
                    if len(g.messages) < self._max_group_size:
                        return g

        # Rule 3: Time window — join the most recent eligible group
        now = msg.timestamp
        for g in reversed(channel_groups):
            if g.released:
                continue
            last_ts = max(m.timestamp for m in g.messages)
            if (now - last_ts) <= self._window_seconds:
                if len(g.messages) < self._max_group_size:
                    return g

        # Create a new group
        new_group = MessageGroup(
            group_id=str(uuid.uuid4()),
            channel_id=msg.channel_id,
        )
        channel_groups.append(new_group)
        return new_group


async def run_tick_loop(buffer: MessageBuffer, interval_seconds: float = 1.0) -> None:
    """Coroutine that calls ``buffer.tick()`` every ``interval_seconds``.

    Run as an asyncio task::

        asyncio.create_task(run_tick_loop(buffer))
    """
    while True:
        await asyncio.sleep(interval_seconds)
        try:
            await buffer.tick()
        except Exception:
            logger.exception("[BUFFER] Unexpected error in tick loop")
