"""Telethon-based Telegram listener for the agent graph.

Extracted from graph.py for maintainability.
Feeds incoming Telegram messages into the compiled agent graph.
"""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any

from telegram_signal_copier.adapters.telegram_client import _normalize_source_name
from telegram_signal_copier.agents.schemas import AgentState
from telegram_signal_copier.config import AppConfig
from telegram_signal_copier.services import message_logger as _msg_logger

from telegram_signal_copier.agents.graph import run_on_message

logger = logging.getLogger(__name__)


async def start_listener(
    compiled_graph: Any,
    config: AppConfig,
    session_path: str | None = None,
) -> None:  # pragma: no cover
    """Async Telethon listener that feeds incoming messages into the graph."""
    try:
        from telethon import TelegramClient, events  # type: ignore[import]
        from telethon.tl.types import MessageMediaPhoto, MessageMediaDocument  # type: ignore[import]
    except ImportError as exc:
        raise RuntimeError("telethon required: uv pip install telethon") from exc

    import os
    api_id   = int(config.telegram_api_id or 0)
    api_hash = config.telegram_api_hash or ""
    session = session_path or config.telegram_session_name
    if not os.path.isabs(str(session)):
        session = str(config.project_root / session)

    client = TelegramClient(session, api_id, api_hash)

    from telegram_signal_copier.config import _parse_source_spec  # type: ignore[attr-defined]

    source_ids: set[str] = set()
    source_numeric_ids: set[str] = set()
    source_usernames: set[str] = set()
    for src in config.telegram_sources:
        label, identifier = _parse_source_spec(src)
        source_ids.add(_normalize_source_name(label))
        ident = identifier.lstrip("@").strip()
        is_numeric = False
        try:
            int(ident)
            is_numeric = True
        except ValueError:
            pass

        if is_numeric:
            source_numeric_ids.add(ident)
        elif ident:
            source_usernames.add(ident.lower())

    media_dir = config.project_root / "runtime" / "media"
    media_dir.mkdir(parents=True, exist_ok=True)

    _msg_logger.init(config.project_root / "logs")

    logger.info("[LISTENER] Connecting session=%s sources=%s", session, source_ids)
    await client.start(phone=config.telegram_phone_number)
    logger.info("[LISTENER] Connected.")

    @client.on(events.NewMessage())
    async def _handler(event: Any) -> None:
        try:
            chat = await event.get_chat()
            chat_title: str = (
                getattr(chat, "title", "")
                or getattr(chat, "username", "")
                or str(chat.id)
            )

            if source_ids or source_numeric_ids or source_usernames:
                username = (getattr(chat, "username", "") or "").lower().lstrip("@")
                chat_id_str = str(chat.id) if hasattr(chat, "id") else ""
                normalized_title = _normalize_source_name(chat_title)

                def numeric_match(cid: str, target_set: set[str]) -> bool:
                    if not cid:
                        return False
                    try:
                        c_val = int(cid)
                        for target in target_set:
                            try:
                                t_val = int(target)
                                if c_val == t_val:
                                    return True
                                s_c = str(c_val)
                                s_t = str(t_val)
                                if s_c.startswith("-100") and s_c[4:] == s_t:
                                    return True
                                if s_t.startswith("-100") and s_t[4:] == s_c:
                                    return True
                            except ValueError:
                                continue
                    except ValueError:
                        pass
                    return False

                if not (
                    normalized_title in source_ids
                    or username in source_usernames
                    or chat_id_str in source_numeric_ids
                    or numeric_match(chat_id_str, source_numeric_ids)
                ):
                    return

            raw_text: str = event.message.message or ""
            message_id: str = str(event.message.id)
            chat_id_for_log = str(chat.id) if hasattr(chat, "id") else ""

            _raw_logger = _msg_logger.get()
            if _raw_logger is not None:
                _raw_logger.log(
                    source_group=chat_title,
                    message_id=message_id,
                    chat_id=chat_id_for_log,
                    raw_text=raw_text,
                    has_image=bool(event.message.media),
                )

            image_path: str | None = None
            media = event.message.media
            if media and isinstance(media, (MessageMediaPhoto, MessageMediaDocument)):
                try:
                    dest = media_dir / f"{message_id}.jpg"
                    await client.download_media(event.message, file=str(dest))
                    if dest.exists():
                        image_path = str(dest)
                        logger.info("[LISTENER] Image saved: %s", dest.name)
                except Exception as dl_err:
                    logger.warning("[LISTENER] Image download failed: %s", dl_err)

            logger.info(
                "[LISTENER] msg source=%r id=%s len=%d image=%s",
                chat_title, message_id, len(raw_text), image_path is not None,
            )

            loop = asyncio.get_event_loop()
            final_state: AgentState = await loop.run_in_executor(
                None,
                lambda: run_on_message(
                    compiled_graph,
                    raw_text=raw_text,
                    source_group=chat_title,
                    message_id=message_id,
                    image_path=image_path,
                ),
            )

            logger.info(
                "[LISTENER] done msg_id=%s intent=%s status=%s ticket=%s",
                message_id,
                final_state.intent,
                final_state.execution_status,
                final_state.order_ticket,
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception("[LISTENER] Unhandled error: %s", exc)

    await client.run_until_disconnected()
