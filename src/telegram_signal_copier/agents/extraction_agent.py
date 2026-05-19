"""Ingestion & Extraction Agent with vision support.

Handles both text-only signals and chart images (TradingView, MT5 mobile).
When an image is attached it is base64-encoded and sent to the LLM as a
vision message alongside the caption text (which may be empty).

Image types understood:
- TradingView chart:  green box = TP zone, red box = SL zone, title bar has symbol
- MT5 chart:          dashed SL lines labelled "SL", TP lines labelled "TP"
- MT5 trade card:     already-placed trade — pass to intent filter, not here

The LLM must return a strict JSON object matching ExtractedSignal.  Any
parse failure routes to the rejection node rather than executing a bad trade.
"""
from __future__ import annotations

import base64
import json
import logging
import mimetypes
from pathlib import Path
from typing import Any

from telegram_signal_copier.agents._llm_shim import SimpleLLM
from telegram_signal_copier.agents.schemas import AgentState, ExtractedSignal

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = """\
You are a financial signal parser for an automated trading system.
Your ONLY job: extract trade parameters from the message (text + optional chart image)
and return a single JSON object.  No commentary outside the JSON block.

Return exactly this JSON structure:
{
  "symbol_raw": "<instrument as stated, e.g. Gold, XAU, XAUUSD, EURUSD, BTC>",
  "side": "<BUY or SELL>",
  "order_type": "<MARKET | BUY_LIMIT | SELL_LIMIT | BUY_STOP | SELL_STOP>",
  "entry_price": <number or null>,
  "stop_loss": <number or null>,
  "take_profits": [<number>, ...],
  "confidence": <0.0 to 1.0>,
  "notes": ["<warnings or observations>"]
}

=== PARSING RULES ===

TEXT SIGNALS:
- "Buy" / "Long" → side=BUY; "Sell" / "Short" → side=SELL
- "NEAR 4703-4701" or "@ 4703-4701" → entry_price = midpoint (4702), order_type = BUY_LIMIT / SELL_LIMIT
- Single entry price given → BUY_LIMIT / SELL_LIMIT for pending, MARKET for "now" / "market"
- "SL:-4699" or "SL:4699" or "SL 4699" or "STOP 4699" → stop_loss = 4699
- "TP 4750" or "TP1 4745 TP2 4750" → collect all into take_profits array (nearest first)
- Partial signals (no TP) are still extracted; set confidence < 0.7 and note missing field
- If stop_loss is absent → stop_loss=null, confidence < 0.5, note "no SL"

CHART IMAGES (TradingView / MT5):
- Read the symbol from the chart title bar (e.g. "XAUUSD · M5", "Gold Spot / U.S. Dollar")
- Green shaded box / green dashed line = TP zone: use TOP edge as take_profit
- Red shaded box / red dashed line = SL zone: use BOTTOM edge as stop_loss  
- Orange dashed line labelled "SL" = stop_loss level
- Blue dashed line labelled "TP" or "BUY" = take_profit or entry level
- The current price (right y-axis, highlighted box) is the approximate entry if no explicit entry is drawn
- Infer BUY if green box is above current price; SELL if red box is above current price
- Set confidence = 0.7 if levels are read from chart, 0.9 if also confirmed by caption text

NON-SIGNAL IMAGES (return all nulls + low confidence):
- If the image is an MT5 positions/history list, broker logo, promo banner, or Telegram chat screenshot
  → return symbol_raw=null, side=null, entry_price=null, stop_loss=null, take_profits=[], confidence=0.1,
    notes=["non-signal image: <type>"]
"""


# ---------------------------------------------------------------------------
# Vision helpers
# ---------------------------------------------------------------------------


def _encode_image(image_path: str) -> tuple[str, str]:
    """Return (base64_data, mime_type) for a local image file."""
    path = Path(image_path)
    mime = mimetypes.guess_type(str(path))[0] or "image/jpeg"
    data = base64.b64encode(path.read_bytes()).decode("utf-8")
    return data, mime


def _build_messages(raw_text: str, image_path: str | None, extra_images: list[str]) -> list:
    """Build LangChain message list with optional inline images."""
    human_content: list[dict[str, Any]] = []

    # Text part
    text_body = raw_text.strip() or "(no caption — analyse the chart image only)"
    human_content.append({"type": "text", "text": text_body})

    # Images
    all_images = []
    if image_path:
        all_images.append(image_path)
    all_images.extend(extra_images or [])

    for img_path in all_images[:4]:  # cap at 4 images per LLM call
        try:
            b64, mime = _encode_image(img_path)
            human_content.append({
                "type": "image_url",
                "image_url": {"url": f"data:{mime};base64,{b64}", "detail": "high"},
            })
        except Exception as exc:
            logger.warning("[EXTRACT] Could not encode image %s: %s", img_path, exc)

    return [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user",   "content": human_content},
    ]


# ---------------------------------------------------------------------------
# Agent node function
# ---------------------------------------------------------------------------


def extraction_agent_node(state: AgentState, llm: SimpleLLM) -> dict[str, Any]:
    """LangGraph node: extract structured trade signal from text and/or chart image."""
    has_image = bool(state.image_path or state.image_paths)
    logger.info(
        "[EXTRACT] source=%s msg_id=%s text_len=%d has_image=%s",
        state.source_group, state.message_id, len(state.raw_text), has_image,
    )

    if not state.raw_text.strip() and not has_image:
        logger.warning("[EXTRACT] Empty message (no text, no image) — routing to reject")
        return {"extraction_error": "Empty message body", "next_node": "reject"}

    extra = list(state.image_paths or [])
    # Don't duplicate primary image in extras
    if state.image_path and state.image_path in extra:
        extra.remove(state.image_path)

    messages = _build_messages(state.raw_text, state.image_path, extra)

    try:
        response = llm.invoke(messages)
        raw_content: str = response.content  # type: ignore[attr-defined]

        # Strip markdown code fences
        cleaned = raw_content.strip()
        if cleaned.startswith("`"):
            lines = cleaned.splitlines()
            cleaned = "\n".join(lines[1:-1] if lines[-1].strip() == "`" else lines[1:])

        data = json.loads(cleaned)
        signal = ExtractedSignal.from_dict(data)

        logger.info(
            "[EXTRACT] OK symbol_raw=%r side=%s order_type=%s entry=%s sl=%s tp=%s conf=%.2f",
            signal.symbol_raw, signal.side, signal.order_type,
            signal.entry_price, signal.stop_loss, signal.take_profits, signal.confidence,
        )
        return {"extracted_signal": signal, "next_node": "validate"}

    except (json.JSONDecodeError, ValueError, KeyError) as exc:
        logger.error("[EXTRACT] Schema parse failed: %s", exc)
        return {"extraction_error": f"Schema parse failed: {exc}", "next_node": "reject"}
    except Exception as exc:  # noqa: BLE001
        logger.error("[EXTRACT] LLM call failed: %s", exc)
        return {"extraction_error": f"LLM call failed: {exc}", "next_node": "reject"}
