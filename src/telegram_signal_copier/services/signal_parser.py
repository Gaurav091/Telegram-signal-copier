from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from telegram_signal_copier.adapters.openai_client import OpenAIClient
from telegram_signal_copier.config import AppConfig
from telegram_signal_copier.models import ParsedSignal, TelegramSignalMessage


PRICE_PATTERN = re.compile(r"\b\d{1,6}(?:\.\d{1,5})?\b")
SL_PATTERN = re.compile(
    r"(?:\bSL\b|\bS\s*[\\/]\s*L\b|STOP\s*LOSS)\s*[:=@-]?\s*(\d{1,6}(?:\.\d{1,5})?)",
    re.IGNORECASE,
)
TP_PATTERN = re.compile(
    r"(?:\bTP\d*\b|\bT\s*[\\/]\s*P\d*\b|TAKE\s*PROFIT\s*\d*)\s*[:=@-]?\s*(\d{1,6}(?:\.\d{1,5})?)",
    re.IGNORECASE,
)
ENTRY_PATTERN = re.compile(r"(?:ENTRY|AT|BUY|SELL)\s*[:=@-]?\s*(\d{1,6}(?:\.\d{1,5})?)", re.IGNORECASE)
AT_SYMBOL_PATTERN = re.compile(r"@\s*(\d{1,6}(?:\.\d{1,5})?)", re.IGNORECASE)

# Cluster context block injected by MessageClusterAgent
_CLUSTER_BLOCK_RE = re.compile(
    r"\[CLUSTER CONTEXT\](.*?)\[/CLUSTER CONTEXT\]",
    re.DOTALL | re.IGNORECASE,
)
_CLUSTER_KV_RE = re.compile(r"^(\w[\w\s]*):\s*(.+)$", re.MULTILINE)


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
        if not symbol:
            return None
        s = str(symbol).strip().upper()
        # common broker suffix patterns, e.g. XAUUSDm or XAUUSD.M -> strip trailing 'M' or '.M' or '-M'
        for suf in ('.M', '-M', 'M'):
            if s.endswith(suf):
                return s[: -len(suf)]
        return s

    def parse(self, message: TelegramSignalMessage, image_text: str = "", image_ai_payload: dict | None = None) -> ParseResult:
        combined_text = "\n".join(part for part in [message.raw_text, image_text] if part).strip()
        heuristic = self._heuristic_parse(message, combined_text)

        # If image analysis already produced a structured AI payload, reuse it
        if image_ai_payload is not None:
            try:
                ai_signal = self._from_ai_payload(message, combined_text, image_ai_payload)
                merged = self._merge_signals(ai_signal, heuristic)
                merged = self._fill_missing_levels_from_chart(merged, message)
                return ParseResult(signal=merged, used_ai=True)
            except Exception as exc:
                heuristic.notes.append(f"AI image payload processing failed; using heuristic fallback: {exc}")
                return ParseResult(signal=heuristic, used_ai=False)

        # Otherwise, if AI client is configured, call it
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
                ai_signal = self._from_ai_payload(message, combined_text, payload)
                merged = self._merge_signals(ai_signal, heuristic)
                merged = self._fill_missing_levels_from_chart(merged, message)
                return ParseResult(signal=merged, used_ai=True)
            except Exception as exc:
                heuristic.notes.append(f"AI parse failed, used heuristic fallback: {exc}")
                return ParseResult(signal=heuristic, used_ai=False)

        return ParseResult(signal=heuristic, used_ai=False)

    def _fill_missing_levels_from_chart(self, signal: ParsedSignal, message: TelegramSignalMessage) -> ParsedSignal:
        if not message.image_path:
            return signal
        needs_sl = signal.stop_loss is None
        needs_tp = not signal.take_profits
        if not needs_sl and not needs_tp:
            return signal
        if not self.ai_client:
            return signal
        try:
            levels = self.ai_client.extract_chart_levels(
                image_path=message.image_path,
                symbol=signal.symbol,
                side=signal.side,
                entry_price=signal.entry_price,
            )
            chart_sl = self._maybe_float(levels.get("stop_loss"))
            raw_tps = levels.get("take_profits") or []
            if not isinstance(raw_tps, list):
                raw_tps = []
            chart_tps = [float(v) for v in raw_tps if v not in (None, "")]
            chart_confidence = max(0.0, min(1.0, float(levels.get("confidence") or 0)))

            if chart_confidence < 0.30:
                signal.notes.append(
                    f"Chart level extraction confidence too low ({chart_confidence:.2f}), skipped"
                )
                return signal

            filled: list[str] = []
            if needs_sl and chart_sl is not None:
                signal = ParsedSignal(
                    source_group=signal.source_group,
                    message_id=signal.message_id,
                    symbol=signal.symbol,
                    side=signal.side,
                    order_type=signal.order_type,
                    entry_price=signal.entry_price,
                    entry_range_low=signal.entry_range_low,
                    entry_range_high=signal.entry_range_high,
                    stop_loss=chart_sl,
                    take_profits=signal.take_profits,
                    confidence=signal.confidence,
                    raw_text=signal.raw_text,
                    image_used=True,
                    requires_review=True,
                    parser_name=signal.parser_name,
                    notes=signal.notes,
                )
                filled.append(f"SL {chart_sl} (from chart)")
            if needs_tp and chart_tps:
                signal = ParsedSignal(
                    source_group=signal.source_group,
                    message_id=signal.message_id,
                    symbol=signal.symbol,
                    side=signal.side,
                    order_type=signal.order_type,
                    entry_price=signal.entry_price,
                    entry_range_low=signal.entry_range_low,
                    entry_range_high=signal.entry_range_high,
                    stop_loss=signal.stop_loss,
                    take_profits=chart_tps,
                    confidence=signal.confidence,
                    raw_text=signal.raw_text,
                    image_used=True,
                    requires_review=True,
                    parser_name=signal.parser_name,
                    notes=signal.notes,
                )
                filled.append(f"TPs {chart_tps} (from chart)")
            if filled:
                signal.notes.append(f"Chart image supplemented missing levels: {', '.join(filled)}")
        except Exception as exc:
            signal.notes.append(f"Chart level extraction failed: {exc}")
        return signal

    def _merge_signals(self, ai_signal: ParsedSignal, heuristic_signal: ParsedSignal) -> ParsedSignal:
        # Use merged allowed symbols (includes dynamic additions). Accept broker suffix variants like 'M'.
        allowed_bases = {self._strip_broker_suffix(symbol) for symbol in (self.config.merged_allowed_symbols or [])}
        symbol = ai_signal.symbol or heuristic_signal.symbol
        symbol_base = self._strip_broker_suffix(symbol)
        heuristic_base = self._strip_broker_suffix(heuristic_signal.symbol)
        if symbol and allowed_bases and (symbol_base not in allowed_bases) and heuristic_signal.symbol and heuristic_base in allowed_bases:
            symbol = heuristic_signal.symbol

        confidence = ai_signal.confidence if ai_signal.confidence > 0 else heuristic_signal.confidence
        notes = list(ai_signal.notes)
        for note in heuristic_signal.notes:
            if note not in notes:
                notes.append(note)
        if ai_signal.confidence <= 0 and heuristic_signal.confidence > 0:
            notes.append("AI confidence missing, reused heuristic confidence")

        merged = ParsedSignal(
            source_group=ai_signal.source_group,
            message_id=ai_signal.message_id,
            symbol=symbol,
            side=ai_signal.side or heuristic_signal.side,
            order_type=ai_signal.order_type or heuristic_signal.order_type,
            entry_price=ai_signal.entry_price if ai_signal.entry_price is not None else heuristic_signal.entry_price,
            entry_range_low=ai_signal.entry_range_low if ai_signal.entry_range_low is not None else heuristic_signal.entry_range_low,
            entry_range_high=ai_signal.entry_range_high if ai_signal.entry_range_high is not None else heuristic_signal.entry_range_high,
            stop_loss=ai_signal.stop_loss if ai_signal.stop_loss is not None else heuristic_signal.stop_loss,
            take_profits=ai_signal.take_profits or heuristic_signal.take_profits,
            confidence=confidence,
            raw_text=ai_signal.raw_text,
            image_used=ai_signal.image_used or heuristic_signal.image_used,
            requires_review=ai_signal.requires_review,
            parser_name="openai+heuristic",
            notes=notes,
        )
        return merged

    def _from_ai_payload(
        self,
        message: TelegramSignalMessage,
        combined_text: str,
        payload: dict[str, Any],
    ) -> ParsedSignal:
        raw_take_profits = payload.get("take_profits") or []
        if not isinstance(raw_take_profits, list):
            raw_take_profits = []
        take_profits = [float(value) for value in raw_take_profits if value not in (None, "")]
        notes = payload.get("notes") or []
        if isinstance(notes, str):
            notes = [notes]
        confidence = self._maybe_float(payload.get("confidence"))
        return ParsedSignal(
            source_group=message.source_group,
            message_id=message.message_id,
            symbol=self._normalize_symbol(payload.get("symbol")),
            side=self._normalize_side(payload.get("side")),
            order_type=str(payload.get("order_type") or "MARKET").upper(),
            entry_price=self._maybe_float(payload.get("entry_price")),
            entry_range_low=self._maybe_float(payload.get("entry_range_low")),
            entry_range_high=self._maybe_float(payload.get("entry_range_high")),
            stop_loss=self._maybe_float(payload.get("stop_loss")),
            take_profits=take_profits,
            confidence=max(0.0, min(1.0, confidence if confidence is not None else 0.0)),
            raw_text=combined_text,
            image_used=bool(message.image_path),
            requires_review=False,
            parser_name="openai",
            notes=[str(note) for note in notes],
        )

    def _heuristic_parse(self, message: TelegramSignalMessage, combined_text: str) -> ParsedSignal:
        upper_text = combined_text.upper()
        symbol = self._detect_symbol(upper_text)
        side = self._normalize_side("BUY" if "BUY" in upper_text or "LONG" in upper_text else "SELL" if "SELL" in upper_text or "SHORT" in upper_text else None)
        order_type = self._detect_order_type(upper_text)

        # --- Entry range support ---
        entry_range_low = None
        entry_range_high = None
        entry_price = None
        # First, match 'NEAR 4542/4545' or '4542/4545' or '4542 - 4545'
        entry_range_match = re.search(r"(?:NEAR|AROUND)?\s*(\d{4,6})\s*[/\-]\s*(\d{4,6})", upper_text)
        if entry_range_match:
            entry_range_low = float(entry_range_match.group(1))
            entry_range_high = float(entry_range_match.group(2))
            entry_price = round((entry_range_low + entry_range_high) / 2, 2)
        else:
            # Also accept two adjacent prices on the same line when near BUY/SELL/ENTRY keywords,
            # e.g. 'XAUUSD SELL NOW: 4582 4586'
            for line in combined_text.splitlines():
                line_u = line.upper()
                if re.search(r"\b(ENTRY|AT|BUY|SELL|NOW|NEAR|AROUND)\b", line_u):
                    pair = re.search(r"(\d{3,7})\s+(\d{3,7})", line_u)
                    if pair:
                        try:
                            l = float(pair.group(1))
                            h = float(pair.group(2))
                            # reject if either value looks like a volume (< 100)
                            if l >= 100 and h >= 100:
                                entry_range_low = l
                                entry_range_high = h
                                entry_price = round((entry_range_low + entry_range_high) / 2, 2)
                                break
                        except Exception:
                            pass
            # fallback to single entry 'ENTRY 4540' or '@4540' patterns
            if entry_price is None:
                raw_entries = ENTRY_PATTERN.findall(upper_text)
                # discard volume-like values (< 100)
                valid_entries = [v for v in raw_entries if self._maybe_float(v) is not None and float(v) >= 100]
                entry_price = self._first_float(valid_entries)
                if entry_price is None:
                    raw_at = AT_SYMBOL_PATTERN.findall(upper_text)
                    valid_at = [v for v in raw_at if self._maybe_float(v) is not None and float(v) >= 100]
                    entry_price = self._first_float(valid_at)

        # --- SL/TP extraction (multi-line robust) ---
        stop_loss = None
        take_profits = []
        # Accept 'SL 4550' and 'TP 4536' on separate lines
        for line in combined_text.splitlines():
            line_u = line.upper()
            if not stop_loss:
                m = SL_PATTERN.search(line_u)
                if m:
                    try:
                        stop_loss = float(m.group(1))
                    except Exception:
                        pass
            tps = TP_PATTERN.findall(line_u)
            for tp in tps:
                try:
                    tp_val = float(tp)
                    if tp_val not in take_profits:
                        take_profits.append(tp_val)
                except Exception:
                    pass

        # If still missing TPs, fallback to price pattern
        if not take_profits:
            numbers = [float(value) for value in PRICE_PATTERN.findall(upper_text)]
            protected = {value for value in [entry_price, stop_loss] if value is not None}
            take_profits = [value for value in numbers if value not in protected][1:3]

        # Overlay cluster-context levels (if MessageClusterAgent injected them)
        ctx = self._parse_cluster_context(combined_text)
        if ctx:
            symbol = ctx.get("symbol") or symbol
            side = self._normalize_side(ctx.get("side")) or side
            if ctx.get("order_type"):
                order_type = ctx["order_type"]
            if ctx.get("entry") is not None:
                entry_price = ctx["entry"]
            if ctx.get("sl") is not None:
                stop_loss = ctx["sl"]
            if ctx.get("tps"):
                take_profits = ctx["tps"]

        fields_found = sum(
            1
            for item in [symbol, side, order_type, entry_price, stop_loss, take_profits[0] if take_profits else None]
            if item not in (None, "")
        )
        confidence = min(0.95, 0.25 + fields_found * 0.12)
        notes: list[str] = []
        if entry_range_low and entry_range_high:
            notes.append(f"Entry range detected: {entry_range_low}-{entry_range_high}, midpoint={entry_price}")
        if message.image_path:
            notes.append("Image attached; heuristic parser may need AI vision for full accuracy")
        if ctx:
            notes.append("Cluster context applied: " + "; ".join(f"{k}={v}" for k, v in ctx.items() if v))

        return ParsedSignal(
            source_group=message.source_group,
            message_id=message.message_id,
            symbol=symbol,
            side=side,
            order_type=order_type,
            entry_price=entry_price,
            entry_range_low=entry_range_low,
            entry_range_high=entry_range_high,
            stop_loss=stop_loss,
            take_profits=take_profits,
            confidence=confidence,
            raw_text=combined_text,
            image_used=bool(message.image_path),
            parser_name="heuristic",
            notes=notes,
        )

    @staticmethod
    def _parse_cluster_context(text: str) -> dict | None:
        """Extract structured levels from a [CLUSTER CONTEXT] block if present."""
        m = _CLUSTER_BLOCK_RE.search(text)
        if not m:
            return None
        block = m.group(1)
        result: dict = {}
        for kv in _CLUSTER_KV_RE.finditer(block):
            key = kv.group(1).strip().lower()
            val = kv.group(2).strip()
            if key == "symbol":
                result["symbol"] = val
            elif key == "side":
                result["side"] = val
            elif key == "order":
                result["order_type"] = val
            elif key == "entry":
                try:
                    result["entry"] = float(val)
                except ValueError:
                    pass
            elif key == "sl":
                try:
                    result["sl"] = float(val)
                except ValueError:
                    pass
            elif key == "tp":
                nums = re.findall(r"\d{3,7}(?:\.\d{1,5})?", val)
                result["tps"] = [float(n) for n in nums]
        return result if result else None

    def _detect_symbol(self, upper_text: str) -> str | None:
        aliases = {
            "GOLD": "XAUUSD",
            "XAU": "XAUUSD",
            "EU": "EURUSD",
            "GU": "GBPUSD",
            "UJ": "USDJPY",
            "DOW": "US30",
            "DJ30": "US30",
            "DOWJONES": "US30",
            "US 30": "US30",
            "NDX": "NAS100",
            "NASDAQ": "NAS100",
            "NAS 100": "NAS100",
            "NQ": "NAS100",
        }
        for alias, symbol in aliases.items():
            if re.search(rf"\b{re.escape(alias)}\b", upper_text):
                return symbol
        # match configured allowed symbols or their common broker-suffix variants in the text
        for symbol in self.config.merged_allowed_symbols:
            normalized = str(symbol).upper()
            if normalized in upper_text:
                return normalized
            # broker variants like trailing 'M'
            if (normalized + 'M') in upper_text or (normalized + '.M') in upper_text:
                return normalized
        # Fallback: only accept tokens that contain digits (e.g. NAS100, US30)
        # or end with a common currency/code suffix (e.g. USD, EUR, JPY, XAU)
        # This avoids matching generic words like 'ACTIVE' from headers.
        match = re.search(r"\b([A-Z0-9]{3,10}(?:\d+|USD|EUR|JPY|GBP|AUD|CAD|NZD|CHF|XAU|XAG))\b", upper_text)
        return match.group(1) if match else None

    @staticmethod
    def _detect_order_type(upper_text: str) -> str:
        for candidate in ["BUY LIMIT", "SELL LIMIT", "BUY STOP", "SELL STOP"]:
            if candidate in upper_text:
                return candidate.replace(" ", "_")
        return "MARKET"

    @staticmethod
    def _first_float(values: list[str]) -> float | None:
        return float(values[0]) if values else None

    @staticmethod
    def _maybe_float(value: Any) -> float | None:
        if value in (None, ""):
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _normalize_side(value: Any) -> str | None:
        if value is None:
            return None
        normalized = str(value).strip().upper()
        if normalized == "LONG":
            return "BUY"
        if normalized == "SHORT":
            return "SELL"
        return normalized if normalized in {"BUY", "SELL"} else None

    @staticmethod
    def _normalize_symbol(value: Any) -> str | None:
        if value in (None, ""):
            return None
        normalized = str(value).strip().upper()
        aliases = {
            "GOLD": "XAUUSD",
            "XAU": "XAUUSD",
            "EU": "EURUSD",
            "GU": "GBPUSD",
            "UJ": "USDJPY",
            "DOW": "US30",
            "DJ30": "US30",
            "DOWJONES": "US30",
            "NDX": "NAS100",
            "NASDAQ": "NAS100",
            "NQ": "NAS100",
        }
        return aliases.get(normalized, normalized)