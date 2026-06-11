"""Signal parser facade — coordinates heuristic and AI-based signal extraction.

Delegates to:
  signals.heuristic  — rule-based parsing, MT5 screenshots, early exits
  signals.ai_merge   — AI payload conversion, range-aware merge, chart fill
  signals.normalizers — symbol/side/OCR normalization utilities
  signals.patterns    — regex patterns and constants
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from telegram_signal_copier.adapters.openai_client import OpenAIClient
from telegram_signal_copier.config import AppConfig
from telegram_signal_copier.models import ParsedSignal, TelegramSignalMessage
from telegram_signal_copier.services.signals.ai_merge import (
    fill_missing_levels_from_chart,
    from_ai_payload,
    merge_signals,
)
from telegram_signal_copier.services.signals.heuristic import heuristic_parse
from telegram_signal_copier.services.signals.ocr_extractor import extract_signal_from_image
from telegram_signal_copier.services.signals.normalizers import (
    normalize_ocr_spaced_numbers,
    normalize_side,
    normalize_symbol,
    strip_broker_suffix,
    maybe_float,
    first_float,
    detect_order_type,
)


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

        # If AI payload provided, use it
        if image_ai_payload is not None:
            try:
                ai_signal = from_ai_payload(message, combined_text, image_ai_payload)
                merged = merge_signals(self.config, ai_signal, heuristic)
                merged = fill_missing_levels_from_chart(self.ai_client, merged, message)
                return ParseResult(signal=merged, used_ai=True)
            except Exception as exc:
                heuristic.notes.append(f"AI image payload processing failed; using heuristic fallback: {exc}")
                return ParseResult(signal=heuristic, used_ai=False)

        # Try AI client first if available
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
                heuristic.notes.append(f"AI parse failed, attempting local OCR fallback: {exc}")
                # Fall through to OCR extractor

        # Use local OCR extractor for images when AI fails or is unavailable
        if message.image_path:
            try:
                ocr_signal = extract_signal_from_image(self.config, message)
                # Merge OCR results with heuristic for best coverage
                if ocr_signal.confidence > 0.3:
                    merged = merge_signals(self.config, ocr_signal, heuristic)
                    merged.notes.append("Local OCR extraction used (no AI dependency)")
                    return ParseResult(signal=merged, used_ai=False)
                else:
                    heuristic.notes.append("OCR extraction returned low confidence; using heuristic only")
            except Exception as exc:
                heuristic.notes.append(f"OCR extraction failed: {exc}")

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
