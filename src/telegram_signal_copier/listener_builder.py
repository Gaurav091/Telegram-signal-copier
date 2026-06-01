"""Backward-compatibility shim — build_pipeline moved to listener.builder."""
from telegram_signal_copier.listener.builder import build_pipeline as build_pipeline  # noqa: F401
