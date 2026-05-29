"""Intent classification helpers for CopierPipeline.

Extracted from pipeline.py to keep each module under 300 lines.
"""
from __future__ import annotations

import logging

from telegram_signal_copier.models import TelegramSignalMessage
from telegram_signal_copier.services.intent_classifier import (
    INFO_INTENTS,
    NEW_SIGNAL_OVERRIDE,
    TRADE_UPDATE_OVERRIDE,
    UPDATE_INTENTS,
)

logger = logging.getLogger(__name__)


def classify_message_intent(
    signal_parser: object,
    message: TelegramSignalMessage,
    primary_image: str | None,
    combined_text: str,
) -> tuple[str, float, str, bool]:
    """Classify the intent of an incoming message.

    Returns ``(intent, confidence, reasoning, force_skip_trade_update)``.
    """
    intent = "UNKNOWN"
    intent_confidence = 0.0
    reasoning = ""
    force_skip_trade_update = False

    # Hard override: caption explicitly signals a new trade entry.
    if NEW_SIGNAL_OVERRIDE.search(combined_text):
        intent = "NEW_TRADE_SIGNAL"
        intent_confidence = 1.0
        reasoning = f"Keyword override from caption: {combined_text[:60]!r}"
        logger.info("[INTENT] FORCED NEW_TRADE_SIGNAL — keyword match in caption: %r", combined_text[:60])
        return intent, intent_confidence, reasoning, force_skip_trade_update

    if TRADE_UPDATE_OVERRIDE.search(combined_text):
        intent = "TRADE_UPDATE"
        intent_confidence = 1.0
        reasoning = f"Trade-update override from caption: {combined_text[:60]!r}"
        force_skip_trade_update = True
        logger.info("[INTENT] FORCED TRADE_UPDATE — keyword match in caption: %r", combined_text[:60])
        return intent, intent_confidence, reasoning, force_skip_trade_update

    # Heuristic preview on text-only messages before burning an AI call.
    has_image = bool(primary_image)
    if not has_image:
        _preview_text = message.raw_text or combined_text
        _preview_signal = signal_parser._heuristic_parse(message, _preview_text)  # type: ignore[attr-defined]
        _preview_complete = bool(
            _preview_signal.side and (
                _preview_signal.entry_price is not None
                or _preview_signal.stop_loss is not None
                or bool(_preview_signal.take_profits)
            )
        )
        if _preview_complete:
            intent = "NEW_TRADE_SIGNAL"
            intent_confidence = min(_preview_signal.confidence + 0.1, 1.0)
            reasoning = "Heuristic preview: complete text signal found — skipped AI intent call"
            logger.info("[INTENT] HEURISTIC_SHORTCUT — complete text signal detected, skipped AI")
            return intent, intent_confidence, reasoning, force_skip_trade_update

    ai_client = getattr(signal_parser, "ai_client", None)
    if intent == "UNKNOWN" and ai_client:
        try:
            intent_result = ai_client.classify_intent(
                raw_text=combined_text,
                image_path=primary_image,
            )
            intent = str(intent_result.get("intent", "UNKNOWN")).upper()
            intent_confidence = float(intent_result.get("confidence", 0.0))
            reasoning = intent_result.get("reasoning", "")
            logger.info("[INTENT] %s (conf=%.2f) — %s", intent, intent_confidence, reasoning)
        except Exception as exc:
            logger.warning("[INTENT] classification failed: %s — treating as UNKNOWN", exc)

    return intent, intent_confidence, reasoning, force_skip_trade_update


__all__ = ["classify_message_intent"]
