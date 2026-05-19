"""Intent Filter Agent — pre-filter before extraction.

Classifies incoming messages as:
  NEW_SIGNAL    → pass to extraction agent
  TRADE_UPDATE  → skip (TP hit, SL hit, position closed)
  INFORMATIONAL → skip (promo banners, broker logos, charts-only analysis)
  UNKNOWN       → pass to extraction agent (safe default)

Uses a fast LLM call with the raw text and optional image.
For text-only messages the decision is often instant (keyword matching).
For image-only messages the LLM inspects the image type.

High-confidence TRADE_UPDATE / INFORMATIONAL messages are skipped;
anything ambiguous is forwarded to avoid missing real signals.
"""
from __future__ import annotations

import logging
import re
from typing import Any

from telegram_signal_copier.agents.schemas import AgentState
from telegram_signal_copier.agents._llm_shim import SimpleLLM

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Hard-coded keyword shortcuts (no LLM needed)
# ---------------------------------------------------------------------------

# Text patterns that always mean the message IS a new tradeable signal
_NEW_SIGNAL_RE = re.compile(
    r"\b(buy\s*(now|limit|stop)?|sell\s*(now|limit|stop)?|long\s*entry|short\s*entry"
    r"|new\s*(trade|signal|entry|setup|call)|open\s*trade)\b",
    re.IGNORECASE,
)

# Text patterns that always mean trade update (skip without LLM)
_UPDATE_RE = re.compile(
    r"\b(tp\s*\d*\s*hit|sl\s*hit|target\s*hit|profit\s*done|trade\s*closed"
    r"|close[d]?\s*trade|move\s*sl\s*to|move\s*stop|partial\s*(close|profit)"
    r"|be\s*secured|breakeven|trailing|update\b)\b",
    re.IGNORECASE,
)

# Confidence thresholds for LLM-based skip decision
_SKIP_THRESHOLD = 0.88  # require very high confidence to skip

# ---------------------------------------------------------------------------
# LLM system prompt for intent classification
# ---------------------------------------------------------------------------

_INTENT_PROMPT = """\
You are an intent classifier for a trading signal copier system.
Given a Telegram message (text + optional chart/screenshot image), classify it.

Return ONLY a JSON object with this exact structure (no extra text):
{
  "intent": "<NEW_SIGNAL | TRADE_UPDATE | INFORMATIONAL>",
  "confidence": <0.0 to 1.0>,
  "reason": "<one line explanation>"
}

INTENT DEFINITIONS:
- NEW_SIGNAL:    A new trade to open (contains entry direction + levels, chart with TP/SL zones)
- TRADE_UPDATE:  Update on an existing trade (TP hit, SL hit, move SL to BE, partial close,
                  MT5 position screenshot, MT5 deal history screenshot, open-trade status image)
- INFORMATIONAL: No trading action needed (broker promo, logo image, subscription offer,
                  educational content, market analysis with no actionable entry)

When in doubt between NEW_SIGNAL and INFORMATIONAL, choose NEW_SIGNAL.
Only choose TRADE_UPDATE or INFORMATIONAL when you are very confident (confidence >= 0.88).
"""


def _keyword_decision(text: str) -> str | None:
    """Fast keyword pre-check. Returns intent string or None (→ use LLM)."""
    if _UPDATE_RE.search(text):
        return "TRADE_UPDATE"
    if _NEW_SIGNAL_RE.search(text):
        return "NEW_SIGNAL"
    return None


def intent_filter_node(state: AgentState, llm: SimpleLLM) -> dict[str, Any]:
    """LangGraph node: classify intent and decide whether to proceed."""
    import json

    text = state.raw_text.strip()
    has_image = bool(state.image_path or state.image_paths)

    # ── Fast keyword check (text only, no LLM) ───────────────────────────
    kw = _keyword_decision(text)
    if kw == "NEW_SIGNAL":
        logger.info("[INTENT] NEW_SIGNAL via keyword shortcut")
        return {"intent": "NEW_SIGNAL", "intent_confidence": 1.0, "next_node": "extract"}
    if kw == "TRADE_UPDATE" and not has_image:
        # Only hard-skip on TRADE_UPDATE if there's no image (image might be a new chart)
        logger.info("[INTENT] TRADE_UPDATE via keyword shortcut (text-only) — skipping")
        return {"intent": "TRADE_UPDATE", "intent_confidence": 1.0, "next_node": "reject"}

    # ── For text-only short messages without buy/sell keywords: skip LLM ─
    # e.g. pure promo text with no numbers
    if not has_image and len(text) < 30 and not re.search(r"\d", text):
        logger.info("[INTENT] Short non-numeric text-only message — forwarding as UNKNOWN")
        return {"intent": "UNKNOWN", "intent_confidence": 0.5, "next_node": "extract"}

    # ── LLM-based classification ──────────────────────────────────────────
    from telegram_signal_copier.agents.extraction_agent import _encode_image

    content: list[dict] = [{"type": "text", "text": text or "(no caption)"}]
    if state.image_path:
        try:
            b64, mime = _encode_image(state.image_path)
            content.append({
                "type": "image_url",
                "image_url": {"url": f"data:{mime};base64,{b64}", "detail": "low"},
            })
        except Exception as exc:
            logger.warning("[INTENT] Could not encode image for intent check: %s", exc)

    messages = [
        {"role": "system", "content": _INTENT_PROMPT},
        {"role": "user",   "content": content},
    ]

    try:
        response = llm.invoke(messages)
        raw = response.content.strip()  # type: ignore[attr-defined]
        if raw.startswith("```"):
            lines = raw.splitlines()
            raw = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
        data = json.loads(raw)
        intent: str = str(data.get("intent", "UNKNOWN")).upper()
        conf: float = max(0.0, min(1.0, float(data.get("confidence", 0.5))))
        reason: str = data.get("reason", "")

        logger.info("[INTENT] %s conf=%.2f — %s", intent, conf, reason)

        if intent in {"TRADE_UPDATE", "INFORMATIONAL"} and conf >= _SKIP_THRESHOLD:
            logger.info("[INTENT] Skipping message: %s (conf=%.2f)", intent, conf)
            return {"intent": intent, "intent_confidence": conf, "next_node": "reject"}

        return {"intent": intent or "UNKNOWN", "intent_confidence": conf, "next_node": "extract"}

    except Exception as exc:  # noqa: BLE001
        logger.warning("[INTENT] Classification failed (%s) — defaulting to extract", exc)
        return {"intent": "UNKNOWN", "intent_confidence": 0.0, "next_node": "extract"}
