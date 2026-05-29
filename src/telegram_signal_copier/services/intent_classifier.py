"""Intent classification for incoming Telegram messages.

Separates the heuristic + AI intent-routing logic from the main pipeline
orchestration so each concern can be tested and modified independently.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from telegram_signal_copier.adapters.openai_client import OpenAIClient
    from telegram_signal_copier.models import ParsedSignal

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Regex overrides — applied before any AI call
# ---------------------------------------------------------------------------

# Caption patterns that hard-force NEW_TRADE_SIGNAL regardless of AI opinion.
# Matches: "New", "NEW", "New Trade", "New Signal", "new entry", "Buy Now", etc.
NEW_SIGNAL_OVERRIDE = re.compile(
    r"\b(new\s*(trade|signal|entry|setup|call|idea)?|buy\s*now|sell\s*now|open\s*trade)\b",
    re.IGNORECASE,
)

# Caption patterns that hard-force TRADE_UPDATE — operational follow-ups that
# are never new entries even when an image is attached.
TRADE_UPDATE_OVERRIDE = re.compile(
    r"\b(exit\s*(both|all)?|close\s*(both|all|trade)?|book\s*profit|tp\s*\d*\s*hit|"
    r"tp\s*\d*\s*done|sl\s*hit|target\s*(hit|done|achieved)|"
    r"all\s*targets?\s*(complete|completed|hit|done|achieved)|targets?\s*complete|"
    r"move\s*sl|move\s*stop|breakeven|break\s*even|partial(?:\s*(close|profit))?|"
    r"trade\s*closed|trade\s*setup\s*invalid|setup\s*invalid|"
    r"cancel(?:led)?\s*(this|the)?\s*(order|trade|setup)?|trail(?:ing)?\s*sl|"
    r"(?:\d+\s*)?pips?\s*(done|booked)|profit\s*done|"
    r"kiss\s*my\s*stop\s*loss|stop\s*loss\s*(hit|kiss(?:ed)?|taken|touched|and\s*fly)|"
    r"congratulation(?:s)?)\b",
    re.IGNORECASE,
)

# Minimum AI confidence needed to auto-skip a text-only message.
INFO_SKIP_THRESHOLD: float = 0.90
UPDATE_SKIP_THRESHOLD: float = 0.90

# Intent buckets
_UPDATE_INTENTS: frozenset[str] = frozenset({"TRADE_UPDATE"})
_INFO_INTENTS: frozenset[str] = frozenset({"INFORMATIONAL"})
_TRADEABLE_INTENTS: frozenset[str] = frozenset({"NEW_TRADE_SIGNAL", "CHART_ANALYSIS", "UNKNOWN"})


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class IntentResult:
    """Outcome of a single intent-classification pass."""

    intent: str
    confidence: float
    reasoning: str
    force_skip: bool = False  # True when a hard-override decided TRADE_UPDATE


# ---------------------------------------------------------------------------
# Classifier
# ---------------------------------------------------------------------------

class IntentClassifier:
    """Classifies the intent of an incoming message into a small set of labels.

    Classification order:
    1. Hard keyword override (regex) — no AI cost.
    2. Heuristic signal preview on text-only messages — no AI cost.
    3. AI ``classify_intent`` call — only when necessary.

    Args:
        ai_client: Optional AI client used for step 3.  Pass ``None`` to
            operate in heuristic-only mode.
    """

    def __init__(self, ai_client: OpenAIClient | None = None) -> None:
        self._ai_client = ai_client

    # ------------------------------------------------------------------
    def classify(
        self,
        text: str,
        has_image: bool,
        *,
        heuristic_signal: ParsedSignal | None = None,
    ) -> IntentResult:
        """Return an :class:`IntentResult` for the given message.

        Args:
            text: Combined message text (raw_text + any OCR output).
            has_image: Whether the message carries at least one image.
            heuristic_signal: Optional pre-computed heuristic parse result.
                When provided and complete (side + at least one level), the
                classifier can shortcut the AI call.
        """
        # ── Step 1: hard regex overrides ─────────────────────────────────
        if NEW_SIGNAL_OVERRIDE.search(text):
            logger.info(
                "[INTENT] FORCED NEW_TRADE_SIGNAL — keyword match in caption: %r",
                text[:60],
            )
            return IntentResult(
                intent="NEW_TRADE_SIGNAL",
                confidence=1.0,
                reasoning=f"Keyword override from caption: {text[:60]!r}",
            )

        if TRADE_UPDATE_OVERRIDE.search(text):
            logger.info(
                "[INTENT] FORCED TRADE_UPDATE — keyword match in caption: %r",
                text[:60],
            )
            return IntentResult(
                intent="TRADE_UPDATE",
                confidence=1.0,
                reasoning=f"Trade-update override from caption: {text[:60]!r}",
                force_skip=True,
            )

        # ── Step 2: heuristic shortcut (text-only, no AI needed) ─────────
        if not has_image and heuristic_signal is not None:
            heuristic_complete = bool(
                heuristic_signal.side and (
                    heuristic_signal.entry_price is not None
                    or heuristic_signal.stop_loss is not None
                    or bool(heuristic_signal.take_profits)
                )
            )
            if heuristic_complete:
                logger.info(
                    "[INTENT] HEURISTIC_SHORTCUT — complete text signal detected, skipped AI"
                )
                return IntentResult(
                    intent="NEW_TRADE_SIGNAL",
                    confidence=min(heuristic_signal.confidence + 0.1, 1.0),
                    reasoning="Heuristic preview: complete text signal found — skipped AI intent call",
                )

        # ── Step 3: AI classification ─────────────────────────────────────
        if self._ai_client is not None:
            primary_image: str | None = None  # image path passed separately by caller
            try:
                result = self._ai_client.classify_intent(raw_text=text, image_path=primary_image)
                intent = str(result.get("intent", "UNKNOWN")).upper()
                confidence = float(result.get("confidence", 0.0))
                reasoning = result.get("reasoning", "")
                logger.info("[INTENT] %s (conf=%.2f) — %s", intent, confidence, reasoning)
                return IntentResult(intent=intent, confidence=confidence, reasoning=reasoning)
            except Exception as exc:
                logger.warning("[INTENT] classification failed: %s — treating as UNKNOWN", exc)

        return IntentResult(intent="UNKNOWN", confidence=0.0, reasoning="No classifier available")

    def classify_with_image(
        self,
        text: str,
        image_path: str | None,
        *,
        heuristic_signal: ParsedSignal | None = None,
    ) -> IntentResult:
        """Like :meth:`classify` but passes *image_path* to the AI client."""
        has_image = bool(image_path)

        # Regex overrides are image-agnostic
        if NEW_SIGNAL_OVERRIDE.search(text):
            logger.info(
                "[INTENT] FORCED NEW_TRADE_SIGNAL — keyword match in caption: %r",
                text[:60],
            )
            return IntentResult(
                intent="NEW_TRADE_SIGNAL",
                confidence=1.0,
                reasoning=f"Keyword override from caption: {text[:60]!r}",
            )

        if TRADE_UPDATE_OVERRIDE.search(text):
            logger.info(
                "[INTENT] FORCED TRADE_UPDATE — keyword match in caption: %r",
                text[:60],
            )
            return IntentResult(
                intent="TRADE_UPDATE",
                confidence=1.0,
                reasoning=f"Trade-update override from caption: {text[:60]!r}",
                force_skip=True,
            )

        if not has_image and heuristic_signal is not None:
            heuristic_complete = bool(
                heuristic_signal.side and (
                    heuristic_signal.entry_price is not None
                    or heuristic_signal.stop_loss is not None
                    or bool(heuristic_signal.take_profits)
                )
            )
            if heuristic_complete:
                logger.info(
                    "[INTENT] HEURISTIC_SHORTCUT — complete text signal detected, skipped AI"
                )
                return IntentResult(
                    intent="NEW_TRADE_SIGNAL",
                    confidence=min(heuristic_signal.confidence + 0.1, 1.0),
                    reasoning="Heuristic preview: complete text signal found — skipped AI intent call",
                )

        if self._ai_client is not None:
            try:
                result = self._ai_client.classify_intent(raw_text=text, image_path=image_path)
                intent = str(result.get("intent", "UNKNOWN")).upper()
                confidence = float(result.get("confidence", 0.0))
                reasoning = result.get("reasoning", "")
                logger.info("[INTENT] %s (conf=%.2f) — %s", intent, confidence, reasoning)
                return IntentResult(intent=intent, confidence=confidence, reasoning=reasoning)
            except Exception as exc:
                logger.warning("[INTENT] classification failed: %s — treating as UNKNOWN", exc)

        return IntentResult(intent="UNKNOWN", confidence=0.0, reasoning="No classifier available")


# Re-export constants that pipeline.py currently reads directly
UPDATE_INTENTS = _UPDATE_INTENTS
INFO_INTENTS = _INFO_INTENTS
TRADEABLE_INTENTS = _TRADEABLE_INTENTS
