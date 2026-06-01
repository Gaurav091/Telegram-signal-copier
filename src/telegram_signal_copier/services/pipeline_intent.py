"""Backward-compatibility shim — classify_message_intent moved to services.pipeline.intent."""
from telegram_signal_copier.services.pipeline.intent import classify_message_intent as classify_message_intent  # noqa: F401
