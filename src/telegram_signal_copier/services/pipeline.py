"""Backward-compatibility shim — CopierPipeline moved to services.pipeline.core."""
from telegram_signal_copier.services.pipeline.core import CopierPipeline as CopierPipeline, PipelineOutcome as PipelineOutcome  # noqa: F401
