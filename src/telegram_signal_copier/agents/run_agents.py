"""Entry-point: run the LangGraph multi-agent Telegram trade copier.

Usage
-----
    python -m telegram_signal_copier.agents.run_agents

Or directly:
    python src/telegram_signal_copier/agents/run_agents.py

Configuration is loaded from the same .env / environment variables as the
existing CopierPipeline (TELEGRAM_API_ID, OPENAI_API_KEY, etc.).
Two extra optional env-vars are supported by the agent pipeline:

    AGENT_OPENAI_BASE_URL   — override LLM base URL (default: https://api.openai.com/v1)
    AGENT_OPENAI_MODEL      — model name (default: gpt-4o-mini)
    AGENT_MIN_RR            — minimum R:R ratio (default: 1.5)
"""
from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path

from telegram_signal_copier.adapters.bridge import FileBridgeExecutor
from telegram_signal_copier.adapters.openai_client import OpenAIClient
from telegram_signal_copier.agents._llm_shim import SimpleLLM
from telegram_signal_copier.agents.graph import build_graph, start_listener
from telegram_signal_copier.config import AppConfig
from telegram_signal_copier.services.pipeline_logger import PipelineLogger

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s — %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


def _build_llm(config: AppConfig) -> SimpleLLM:
    logger.info(
        "[INIT] LLM via OpenAIClient (stdlib) model=%s",
        getattr(config, "openai_model", "gpt-4o-mini"),
    )
    client = OpenAIClient(config)
    return SimpleLLM(client)


async def main() -> None:
    project_root = Path(__file__).resolve().parents[4]  # …/Telegram signal Copier
    config = AppConfig.from_env(project_root)

    llm = _build_llm(config)
    executor = FileBridgeExecutor(
        inbox_dir=config.bridge_inbox_dir,
        outbox_dir=config.bridge_outbox_dir,
        symbol_suffix=getattr(config, "symbol_suffix", ""),
    )

    pipeline_log = PipelineLogger(logs_dir=project_root / "logs")

    graph = build_graph(config, llm, executor, pipeline_log=pipeline_log)
    logger.info("[INIT] Graph compiled — starting Telegram listener…")

    await start_listener(graph, config)


if __name__ == "__main__":
    asyncio.run(main())
