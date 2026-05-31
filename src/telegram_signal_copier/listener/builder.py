"""Pipeline builder — constructs a CopierPipeline from AppConfig.

Extracted from main.py to avoid circular imports with listener_runner.py.
"""
from __future__ import annotations

from telegram_signal_copier.adapters.bridge import FileBridgeExecutor
from telegram_signal_copier.adapters.openai_client import OpenAIClient
from telegram_signal_copier.config import AppConfig
from telegram_signal_copier.services.image_processor import ImageProcessor
from telegram_signal_copier.services.pipeline import CopierPipeline
from telegram_signal_copier.services.pipeline_logger import PipelineLogger
from telegram_signal_copier.services.risk_engine import RiskEngine
from telegram_signal_copier.services.signal_parser import SignalParser


def build_pipeline(config: AppConfig) -> CopierPipeline:
    ai_client = None
    if config.ai_ready:
        ai_client = OpenAIClient(config)
    pipeline_log = PipelineLogger(logs_dir=config.project_root / "logs")
    return CopierPipeline(
        config=config,
        image_processor=ImageProcessor(ai_client=ai_client),
        signal_parser=SignalParser(config=config, ai_client=ai_client),
        risk_engine=RiskEngine(config=config),
        executor=FileBridgeExecutor(
            config.bridge_inbox_dir,
            config.bridge_outbox_dir,
            timeout_seconds=config.mt5_bridge_timeout_seconds,
            symbol_suffix=config.mt5_symbol_suffix,
        ),
        pipeline_logger=pipeline_log,
    )
