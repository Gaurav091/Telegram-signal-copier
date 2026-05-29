"""Agent pipeline — stdlib-only replacement for langgraph.StateGraph.

Graph topology (intent pre-filter → extract → validate → execute)
------------------------------------------------------------------

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

Routing is driven by ``state.next_node`` which each node sets before
returning.  The ``_Pipeline`` class replaces ``langgraph.StateGraph``.
"""
from __future__ import annotations

import asyncio
import logging
from functools import partial
from pathlib import Path
from typing import Any, Optional

from telegram_signal_copier.adapters.bridge import FileBridgeExecutor
from telegram_signal_copier.adapters.telegram_client import _normalize_source_name
from telegram_signal_copier.agents._llm_shim import SimpleLLM
from telegram_signal_copier.services import message_logger as _msg_logger
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
# _Pipeline — lightweight replacement for langgraph.StateGraph
# ---------------------------------------------------------------------------

_TERMINAL = {"end", ""}


class _Pipeline:
    """Sequential pipeline that routes via ``state.next_node``.

    Replaces ``langgraph.StateGraph`` with zero external dependencies.
    The execution model is identical: each node returns a ``dict`` of
    partial-state updates; the pipeline merges them and follows the
    routing flag until it reaches ``"end"``.
    """

    def __init__(
        self,
        nodes: dict[str, Any],
        pipeline_log: Optional[PipelineLogger] = None,
    ) -> None:
        self._nodes = nodes
        self._log = pipeline_log

    def invoke(self, initial_state: AgentState | dict[str, Any], *_a, **_kw) -> AgentState:
        """Run the pipeline synchronously and return the final state."""
        if isinstance(initial_state, dict):
            state = AgentState.from_dict(initial_state)
        else:
            state = initial_state

        current = "intent_filter"
        visited: set[str] = set()

        while current not in _TERMINAL:
            if current in visited:
                logger.error("[PIPELINE] Routing loop detected at node=%s — aborting", current)
                break
            visited.add(current)

            node_fn = self._nodes.get(current)
            if node_fn is None:
                logger.warning("[PIPELINE] Unknown node=%s — stopping", current)
                break

            updates = node_fn(state)
            if isinstance(updates, dict):
                state._apply(updates)

            current = state.next_node or "end"

        if self._log is not None:
            self._emit_log(initial_state, state)

        return state

    # Support attribute-style access so code doing ``graph.invoke(...)``
    # and ``graph.some_other_attr`` still works transparently.
    def __getattr__(self, name: str) -> Any:
        raise AttributeError(f"_Pipeline has no attribute {name!r}")

    def _emit_log(self, initial: Any, state: AgentState) -> None:
        try:
            image_count = 1 if state.image_path else 0
            image_count += len(state.image_paths or [])

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
    llm: SimpleLLM,
    executor: FileBridgeExecutor,
    pipeline_log: Optional[PipelineLogger] = None,
) -> _Pipeline:
    """Build and return the agent pipeline."""
    filter_node   = partial(intent_filter_node,   llm=llm)
    extract_node  = partial(extraction_agent_node, llm=llm)
    validate_node = partial(validation_agent_node, app_config=config)
    execute_node  = partial(execution_agent_node,  executor=executor, app_config=config)

    nodes = {
        "intent_filter": filter_node,
        "extract":        extract_node,
        "validate":       validate_node,
        "execute":        execute_node,
        "reject":         _reject_node,
    }
    return _Pipeline(nodes, pipeline_log=pipeline_log)


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


# Re-export: callers that import start_listener from this module continue to work
from telegram_signal_copier.agents.graph_listener import start_listener as start_listener  # noqa: E402, F401
