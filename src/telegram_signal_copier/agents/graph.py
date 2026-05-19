"""LangGraph multi-agent pipeline for Telegram trade signal copying.

Graph topology (with intent pre-filter)
----------------------------------------

  [START]
     |
     v
  intent_filter ──(TRADE_UPDATE/INFORMATIONAL)──> reject ──> [END]
     |
     v (NEW_SIGNAL / UNKNOWN)
  extract  ──(error)──> reject ──> [END]
     |
     v (success)
  validate ──(rejected)──> reject ──> [END]
     |
     v (approved)
  execute  ──(error)──> reject ──> [END]
     |
     v (success)
   [END]
"""
from __future__ import annotations

import asyncio
import logging
from functools import partial
from pathlib import Path
from typing import Any, Optional

from langchain_openai import ChatOpenAI
from langgraph.graph import END, START, StateGraph

from telegram_signal_copier.adapters.bridge import FileBridgeExecutor
from telegram_signal_copier.agents.extraction_agent import extraction_agent_node
from telegram_signal_copier.agents.execution_agent import execution_agent_node
from telegram_signal_copier.agents.intent_filter import intent_filter_node
from telegram_signal_copier.agents.schemas import AgentState
from telegram_signal_copier.agents.validation_agent import validation_agent_node
from telegram_signal_copier.config import AppConfig
from telegram_signal_copier.services.pipeline_logger import PipelineLogger

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Reject terminal node
# ---------------------------------------------------------------------------

def _reject_node(state: AgentState) -> dict[str, Any]:
    reasons = state.rejection_reasons or []
    error = state.extraction_error or state.execution_error
    intent = state.intent
    # Only log WARN for genuine rejections (not routine intent-filter skips)
    if intent in {"TRADE_UPDATE", "INFORMATIONAL"}:
        logger.info(
            "[SKIP] source=%s msg_id=%s intent=%s",
            state.source_group, state.message_id, intent,
        )
    else:
        logger.warning(
            "[REJECT] source=%s msg_id=%s reasons=%s error=%s",
            state.source_group, state.message_id, reasons, error or "unknown",
        )
    return {"next_node": "end"}


# ---------------------------------------------------------------------------
# Conditional edge router
# ---------------------------------------------------------------------------

def _route(state: AgentState) -> str:
    return state.next_node if state.next_node != "end" else END


# ---------------------------------------------------------------------------
# Graph builder
# ---------------------------------------------------------------------------

class _LoggingGraph:
    """Thin wrapper that logs every invocation to ``PipelineLogger``."""

    def __init__(self, compiled_graph: Any, pipeline_log: PipelineLogger) -> None:
        self._graph = compiled_graph
        self._log = pipeline_log

    def invoke(self, initial_state: Any, *args, **kwargs) -> Any:
        result = self._graph.invoke(initial_state, *args, **kwargs)
        self._emit(initial_state, result)
        return result

    # Support any other CompiledGraph methods transparently
    def __getattr__(self, name: str) -> Any:
        return getattr(self._graph, name)

    def _emit(self, initial: Any, result: Any) -> None:
        try:
            state: AgentState
            if isinstance(result, dict):
                state = AgentState.model_validate(result)
            elif isinstance(result, AgentState):
                state = result
            else:
                return

            image_count = 0
            if hasattr(initial, "image_path") and initial.image_path:
                image_count += 1
            if hasattr(initial, "image_paths"):
                image_count += len(initial.image_paths or [])

            action = "IGNORE"
            if state.execution_status in ("FILLED", "SUBMITTED", "DRY_RUN"):
                action = "OPEN_TRADE"
            elif state.rejection_reasons:
                action = "REJECTED"

            self._log.log(
                group_id=state.message_id or "unknown",
                channel_id=0,
                message_count=1,
                image_count=image_count,
                intent=state.intent,
                intent_confidence=state.intent_confidence,
                extraction=state.extracted_signal,
                validation=state.validated_signal,
                rejection_reasons=list(state.rejection_reasons or []),
                action_taken=action,
                execution_status=state.execution_status,
                order_ticket=state.order_ticket,
                execution_error=state.execution_error,
                source_group=state.source_group,
                message_id=state.message_id,
                raw_text_snippet=state.raw_text[:200] if state.raw_text else "",
            )
        except Exception:
            logger.exception("[PIPELINE_LOG] Failed to emit log entry")


def build_graph(
    config: AppConfig,
    llm: ChatOpenAI,
    executor: FileBridgeExecutor,
    pipeline_log: Optional[PipelineLogger] = None,
) -> Any:
    """Compile and return the LangGraph StateGraph."""
    filter_node  = partial(intent_filter_node, llm=llm)
    extract_node = partial(extraction_agent_node, llm=llm)
    validate_node = partial(validation_agent_node, app_config=config)
    execute_node  = partial(execution_agent_node, executor=executor, app_config=config)

    graph = StateGraph(AgentState)
    graph.add_node("intent_filter", filter_node)
    graph.add_node("extract",       extract_node)
    graph.add_node("validate",      validate_node)
    graph.add_node("execute",       execute_node)
    graph.add_node("reject",        _reject_node)

    graph.add_edge(START, "intent_filter")
    graph.add_conditional_edges(
        "intent_filter", _route,
        {"extract": "extract", "reject": "reject", END: END},
    )
    graph.add_conditional_edges(
        "extract", _route,
        {"validate": "validate", "reject": "reject", END: END},
    )
    graph.add_conditional_edges(
        "validate", _route,
        {"execute": "execute", "reject": "reject", END: END},
    )
    graph.add_conditional_edges(
        "execute", _route,
        {"reject": "reject", END: END},
    )
    graph.add_edge("reject", END)

    compiled = graph.compile()

    # Wrap compile result so every invocation is automatically logged.
    if pipeline_log is not None:
        return _LoggingGraph(compiled, pipeline_log)
    return compiled


# ---------------------------------------------------------------------------
# Convenience helpers
# ---------------------------------------------------------------------------

def run_on_message(
    compiled_graph: Any,
    raw_text: str,
    source_group: str = "",
    message_id: str = "",
    image_path: str | None = None,
    image_paths: list[str] | None = None,
) -> AgentState:
    """Synchronously invoke the graph for a single message."""
    initial_state = AgentState(
        raw_text=raw_text,
        source_group=source_group,
        message_id=message_id,
        image_path=image_path,
        image_paths=list(image_paths or []),
    )
    result = compiled_graph.invoke(initial_state)
    if isinstance(result, dict):
        return AgentState.model_validate(result)
    return result  # type: ignore[return-value]


# ---------------------------------------------------------------------------
# Telethon-based Telegram listener
# ---------------------------------------------------------------------------

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

    api_id   = int(config.telegram_api_id or 0)
    api_hash = config.telegram_api_hash or ""
    session  = session_path or config.telegram_session_name

    client = TelegramClient(session, api_id, api_hash)

    source_ids: set[str] = set()
    for src in config.telegram_sources:
        source_ids.add(src.strip().lstrip("@").lower())

    # Where to save downloaded images
    media_dir = config.project_root / "runtime" / "media"
    media_dir.mkdir(parents=True, exist_ok=True)

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

            if source_ids:
                username = (getattr(chat, "username", "") or "").lower()
                if not (
                    chat_title.lower() in source_ids
                    or username in source_ids
                    or str(chat.id) in source_ids
                ):
                    return

            raw_text: str = event.message.message or ""
            message_id: str = str(event.message.id)

            # Download attached image if present
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