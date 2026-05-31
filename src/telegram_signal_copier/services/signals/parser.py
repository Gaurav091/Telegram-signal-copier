"""Signal parser — coordinates heuristic and AI-based signal extraction.

Heavy lifting is split across:
  signal_patterns.py    — regex patterns and constants
  signal_normalizers.py — static normalizer utilities
  signal_crypto.py      — crypto entry price recovery
  signal_heuristic.py   — rule-based (heuristic) parsing
  signal_ai_merge.py    — AI payload processing and signal merging
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from telegram_signal_copier.adapters.openai_client import OpenAIClient
from telegram_signal_copier.config import AppConfig
from telegram_signal_copier.constants import CRYPTO_ENTRY_MIN
from telegram_signal_copier.models import ParsedSignal, TelegramSignalMessage
from telegram_signal_copier.services.signal_ai_merge import (
    fill_missing_levels_from_chart,
    from_ai_payload,
    merge_signals,
)
from telegram_signal_copier.services.signal_heuristic import heuristic_parse
from telegram_signal_copier.services.signal_normalizers import (
    normalize_ocr_spaced_numbers,
    normalize_side,
    normalize_symbol,
    strip_broker_suffix,
    maybe_float,
    first_float,
    detect_order_type,
)
from telegram_signal_copier.services.signal_patterns import (
    AT_SYMBOL_PATTERN,
    CLUSTER_BLOCK_RE,
    CLUSTER_KV_RE,
    ENTRY_PATTERN,
    MT5_SCREENSHOT_HEADER_RE as _MT5_SCREENSHOT_HEADER_RE,
    NEW_TRADE_CAPTIONS as _NEW_TRADE_CAPTIONS,
    OCR_SPACE_NUMBER_RE as _OCR_SPACE_NUMBER_RE,
    PRICE_PATTERN,
    SL_PATTERN,
    SUPERSCRIPT_DIGIT_MAP as _SUPERSCRIPT_DIGIT_MAP,
    TARGET_LINE_PATTERN,
    TP_PATTERN,
)

# Backward-compatible private alias
_CRYPTO_ENTRY_MIN = CRYPTO_ENTRY_MIN


@dataclass(slots=True)
class ParseResult:
    signal: ParsedSignal
    used_ai: bool


class SignalParser:
    def __init__(self, config: AppConfig, ai_client: OpenAIClient | None) -> None:
        self.config = config
        self.ai_client = ai_client

    @staticmethod
    def _strip_broker_suffix(symbol: str | None) -> str | None:
        return strip_broker_suffix(symbol)

    def _heuristic_parse(self, message: TelegramSignalMessage, combined_text: str) -> ParsedSignal:
        return heuristic_parse(self.config, message, combined_text)

    def parse(
        self,
        message: TelegramSignalMessage,
        image_text: str = "",
        image_ai_payload: dict | None = None,
    ) -> ParseResult:
        combined_text = "\n".join(part for part in [message.raw_text, image_text] if part).strip()
        combined_text = normalize_ocr_spaced_numbers(combined_text)
        heuristic = heuristic_parse(self.config, message, combined_text)

        if image_ai_payload is not None:
            try:
                ai_signal = from_ai_payload(message, combined_text, image_ai_payload)
                merged = merge_signals(self.config, ai_signal, heuristic)
                merged = fill_missing_levels_from_chart(self.ai_client, merged, message)
                return ParseResult(signal=merged, used_ai=True)
            except Exception as exc:
                heuristic.notes.append(f"AI image payload processing failed; using heuristic fallback: {exc}")
                return ParseResult(signal=heuristic, used_ai=False)

        if self.ai_client:
            try:
                extra = message.effective_image_paths()
                primary = extra[0] if extra else message.image_path
                rest = extra[1:] if len(extra) > 1 else None
                payload = self.ai_client.parse_signal(
                    combined_text or "Analyze this signal",
                    image_path=primary,
                    all_image_paths=rest,
                )
                ai_signal = from_ai_payload(message, combined_text, payload)
                merged = merge_signals(self.config, ai_signal, heuristic)
                merged = fill_missing_levels_from_chart(self.ai_client, merged, message)
                return ParseResult(signal=merged, used_ai=True)
            except Exception as exc:
                heuristic.notes.append(f"AI parse failed, used heuristic fallback: {exc}")
                return ParseResult(signal=heuristic, used_ai=False)

        return ParseResult(signal=heuristic, used_ai=False)

    # Static backward-compatible method wrappers
    @staticmethod
    def _normalize_ocr_spaced_numbers(text: str) -> str:
        return normalize_ocr_spaced_numbers(text)

    @staticmethod
    def _normalize_symbol(value: Any) -> str | None:
        return normalize_symbol(value)

    @staticmethod
    def _normalize_side(value: Any) -> str | None:
        return normalize_side(value)

    @staticmethod
    def _maybe_float(value: Any) -> float | None:
        return maybe_float(value)

    @staticmethod
    def _first_float(values: list[str]) -> float | None:
        return first_float(values)

    @staticmethod
    def _detect_order_type(upper_text: str) -> str:
        return detect_order_type(upper_text)
