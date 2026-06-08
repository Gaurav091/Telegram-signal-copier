from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from telegram_signal_copier.adapters.openai_client import OpenAIClient
from telegram_signal_copier.config import AppConfig
from telegram_signal_copier.constants import SYMBOL_PRICE_RANGES
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

# MT5 open-position screenshot: "XAUUSD, sell 0.01" header line
_MT5_SCREENSHOT_HEADER_RE = re.compile(
    r"^([A-Z0-9]{4,10}),\s*(buy|sell)\s+[\d.]+",
    re.IGNORECASE | re.MULTILINE,
)
# Normalise OCR thousands-space artifacts: "4 491.53" → "4491.53"
_OCR_SPACE_NUMBER_RE = re.compile(r"(\d{1,4})\s+(\d{3}(?:[.,]\d+)?)(?=\D|$)")

# Caption keywords that signal a new trade from ALGO TRADING forex-style groups
_NEW_TRADE_CAPTIONS = re.compile(r"^\s*(new|both\s*new)\s*$", re.IGNORECASE)

# Multi-target pattern: "Target- 4514, 4520, 4530" or "TP: 4514 4520 4530"
_TARGET_MULTI_RE = re.compile(
    r"(?:target|tp\s*\d*|take\s*profit\s*\d*)[:\s\-]+"
    r"((?:\d{3,7}(?:\.\d{1,5})?(?:\s*[-,/\s]\s*)?)+)",
    re.IGNORECASE,
)

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

        # Prefer heuristic entry/SL/TP when AI values fall outside expected price range
        _sym_for_range = symbol or ai_signal.symbol or heuristic_signal.symbol
        _plo, _phi = SYMBOL_PRICE_RANGES.get(_sym_for_range or "", (0.0, 999999.0))

        def _pick(preferred: float | None, fallback: float | None) -> float | None:
            if preferred is None:
                return fallback
            if fallback is not None and not (_plo <= preferred <= _phi) and (_plo <= fallback <= _phi):
                return fallback
            return preferred

        # Repair entry price when AI dropped leading digits (e.g. 77645→645)
        _entry = _pick(ai_signal.entry_price, heuristic_signal.entry_price)
        _sl = _pick(ai_signal.stop_loss, heuristic_signal.stop_loss)
        _side_merged = ai_signal.side or heuristic_signal.side

        # Prefer heuristic TPs when AI TPs are suspect (out-of-range or inconsistent with SL/entry)
        _ai_tps = ai_signal.take_profits or []
        _h_tps = heuristic_signal.take_profits or []
        if _ai_tps and _h_tps:
            _ai_tps_valid = all(_plo <= t <= _phi for t in _ai_tps)
            _h_tps_valid = all(_plo <= t <= _phi for t in _h_tps)
            # Check directional consistency: for SELL, TPs should be below entry; for BUY, above
            def _tps_consistent(tps: list[float], side: str | None, entry: float | None, sl: float | None) -> bool:
                if not tps or side is None:
                    return True
                ref = entry or sl
                if ref is None:
                    return True
                if side == "SELL" and any(t >= ref for t in tps):
                    return False
                if side == "BUY" and any(t <= ref for t in tps):
                    return False
                return True

            _ai_consistent = _tps_consistent(_ai_tps, _side_merged, _entry, _sl)
            _h_consistent = _tps_consistent(_h_tps, _side_merged, _entry, _sl)
            # MT5 screenshot parser is authoritative — always prefer its TPs over AI
            _h_is_mt5 = heuristic_signal.parser_name == "mt5_screenshot"

            if _h_is_mt5 and _h_tps_valid:
                _tps = _h_tps
                notes.append("MT5 screenshot parser overrode AI-extracted TPs (authoritative source)")
            elif (not _ai_tps_valid or not _ai_consistent) and (_h_tps_valid and _h_consistent):
                _tps = _h_tps
                notes.append("Used heuristic TPs (AI TPs inconsistent with signal direction/range)")
            else:
                _tps = _ai_tps
        else:
            _tps = _ai_tps or _h_tps
        if (
            _entry is not None
            and _sym_for_range
            and not (_plo <= _entry <= _phi)
            and (_sl is not None or _tps)
        ):
            # Try to reconstruct by prepending leading digits from SL/TP
            ref_prices = [p for p in ([_sl] + _tps) if p is not None and _plo <= p <= _phi]
            if ref_prices:
                ref = sum(ref_prices) / len(ref_prices)
                # Reconstruct by trying all 1-3 digit prefixes and picking closest to ref
                # e.g. 645.45 → try d+645.45, d1+d2+645.45, d1+d2+d3+645.45
                best_candidate: float | None = None
                best_dist = float("inf")
                _entry_str = str(_entry)
                # 1-digit prefix
                for d1 in range(1, 10):
                    v1 = float(f"{d1}{_entry_str}")
                    if _plo <= v1 <= _phi:
                        d = abs(v1 - ref)
                        if d < best_dist:
                            best_dist = d
                            best_candidate = v1
                    # 2-digit prefix
                    for d2 in range(0, 10):
                        v2 = float(f"{d1}{d2}{_entry_str}")
                        if _plo <= v2 <= _phi:
                            d = abs(v2 - ref)
                            if d < best_dist:
                                best_dist = d
                                best_candidate = v2
                candidate = best_candidate if best_candidate is not None else _entry
                if _plo <= candidate <= _phi:
                    # Validate direction consistency
                    direction_ok = True
                    if _side_merged == "BUY" and _sl is not None and candidate < _sl:
                        direction_ok = False
                    if _side_merged == "SELL" and _sl is not None and candidate > _sl:
                        direction_ok = False
                    if direction_ok:
                        notes.append(f"Adjusted entry {_entry}→{candidate} (leading digits recovered from SL/TP context)")
                        _entry = candidate

        merged = ParsedSignal(
            source_group=ai_signal.source_group,
            message_id=ai_signal.message_id,
            symbol=symbol,
            side=_side_merged,
            order_type=ai_signal.order_type or heuristic_signal.order_type,
            entry_price=_entry,
            entry_range_low=_pick(ai_signal.entry_range_low, heuristic_signal.entry_range_low),
            entry_range_high=_pick(ai_signal.entry_range_high, heuristic_signal.entry_range_high),
            stop_loss=_sl,
            take_profits=_tps,
            confidence=confidence,
            raw_text=ai_signal.raw_text,
            image_used=ai_signal.image_used or heuristic_signal.image_used,
            requires_review=ai_signal.requires_review,
            parser_name=f"openai+{heuristic_signal.parser_name}" if heuristic_signal.parser_name != "heuristic" else "openai+heuristic",
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

    def _parse_mt5_screenshot(
        self, message: TelegramSignalMessage, combined_text: str
    ) -> ParsedSignal | None:
        """Parse an MT5 open-position screenshot (e.g. 'XAUUSD, sell 0.01 ...\nS/L: ...\nT/P: ...').

        Returns a ParsedSignal when the format is recognised, None otherwise.
        """
        header = _MT5_SCREENSHOT_HEADER_RE.search(combined_text)
        if not header:
            return None

        symbol = self._normalize_symbol(header.group(1))
        side = self._normalize_side(header.group(2))

        # Normalise OCR spacing in numbers before extracting prices
        clean = _OCR_SPACE_NUMBER_RE.sub(lambda m: m.group(1) + m.group(2), combined_text)

        entry_price: float | None = None
        stop_loss: float | None = None
        take_profits: list[float] = []
        for line in clean.splitlines():
            # Extract entry price from "Entry: 77645.45" or "@77645.45" patterns
            if entry_price is None:
                em = re.search(r"(?:ENTRY|PRICE)[:\s=]*@?\s*(\d{3,7}(?:\.\d{1,5})?)", line, re.IGNORECASE)
                if em:
                    try:
                        entry_price = float(em.group(1))
                    except Exception:
                        pass
            # MT5 position card: "4499.54 - 4499.47" or "4499.54 > 4499.47" (current vs open price)
            if entry_price is None and not re.search(r"(?:S/L|T/P|SL|TP|STOP|PROFIT)", line, re.IGNORECASE):
                pm = re.search(r"(\d{3,7}(?:\.\d{1,5})?)\s*[-–>]+\s*(\d{3,7}(?:\.\d{1,5})?)", line)
                if pm:
                    try:
                        entry_price = float(pm.group(1))
                    except Exception:
                        pass
            if not stop_loss:
                m = SL_PATTERN.search(line)
                if m:
                    try:
                        stop_loss = float(m.group(1))
                    except Exception:
                        pass
            for tp in TP_PATTERN.findall(line):
                try:
                    tp_val = float(tp)
                    if tp_val >= 100 and tp_val not in take_profits:
                        take_profits.append(tp_val)
                except Exception:
                    pass

        if not (symbol and side and (entry_price or stop_loss or take_profits)):
            return None

        fields_found = sum(
            1 for v in [symbol, side, entry_price, stop_loss, take_profits[0] if take_profits else None]
            if v not in (None, "")
        )
        confidence = min(0.95, 0.25 + fields_found * 0.12)
        mt5_notes = ["Parsed from MT5 position screenshot format"]
        if entry_price is not None:
            mt5_notes.append(f"Recovered entry from OCR text: {entry_price}")
        return ParsedSignal(
            source_group=message.source_group,
            message_id=message.message_id,
            symbol=symbol,
            side=side,
            order_type="MARKET",
            entry_price=entry_price,
            entry_range_low=None,
            entry_range_high=None,
            stop_loss=stop_loss,
            take_profits=take_profits,
            confidence=confidence,
            raw_text=combined_text,
            image_used=bool(message.image_path),
            parser_name="mt5_screenshot",
            notes=mt5_notes,
        )

    def _heuristic_parse(self, message: TelegramSignalMessage, combined_text: str) -> ParsedSignal:
        # ── OCR preprocessing: normalise thousands-space artifacts ──────────────
        # e.g. "T/P: 4 491.53" → "T/P: 4491.53"  (OCR sometimes splits large numbers)
        combined_text = _OCR_SPACE_NUMBER_RE.sub(
            lambda m: m.group(1) + m.group(2), combined_text
        )

        # ── MT5 position screenshot fast-path ────────────────────────────────────
        # "New" / "Both New" captions from ALGO TRADING forex carry a position card
        # image whose OCR text looks like "XAUUSD, sell 0.01 ... S/L: ... T/P: ...".
        # Detect this format and parse it directly instead of falling through to the
        # generic heuristic which mis-parses the spaced number in "T/P: 4 491.53".
        caption = (message.raw_text or "").strip()
        if _NEW_TRADE_CAPTIONS.match(caption):
            screenshot = self._parse_mt5_screenshot(message, combined_text)
            if screenshot is not None:
                return screenshot

        upper_text = combined_text.upper()
        symbol = self._detect_symbol(upper_text)
        # Detect side from standard keywords first, then custom keywords
        _raw_side = "BUY" if "BUY" in upper_text or "LONG" in upper_text else "SELL" if "SELL" in upper_text or "SHORT" in upper_text else None
        if _raw_side is None:
            # Check custom buy/sell keywords from config
            _custom_buy = [kw.upper() for kw in (getattr(self.config, 'custom_buy_keywords', None) or [])]
            _custom_sell = [kw.upper() for kw in (getattr(self.config, 'custom_sell_keywords', None) or [])]
            for kw in _custom_buy:
                if re.search(rf"\b{re.escape(kw)}\b", upper_text):
                    _raw_side = "BUY"
                    break
            if _raw_side is None:
                for kw in _custom_sell:
                    if re.search(rf"\b{re.escape(kw)}\b", upper_text):
                        _raw_side = "SELL"
                        break
        side = self._normalize_side(_raw_side)
        order_type = self._detect_order_type(upper_text)

        # --- Entry range support ---
        entry_range_low = None
        entry_range_high = None
        entry_price = None
        _has_near_around = bool(re.search(r"\b(NEAR|AROUND)\b", upper_text))
        # First, match 'NEAR 4542/4545' or '4542/4545' or '4542 - 4545'
        entry_range_match = re.search(r"(?:NEAR|AROUND)?\s*(\d{4,6})\s*[/\-]\s*(\d{4,6})", upper_text)
        if entry_range_match:
            a, b = float(entry_range_match.group(1)), float(entry_range_match.group(2))
            entry_range_low = min(a, b)
            entry_range_high = max(a, b)
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
        # Use wide sanity-check range for extraction (strict validation happens later)
        _sym_range = SYMBOL_PRICE_RANGES.get(symbol or "", (0.0, 999999.0))
        _price_lo = max(0.0, _sym_range[0] * 0.3)  # Allow down to 30% of min for historical/test compat
        _price_hi = _sym_range[1] * 2.0  # Allow up to 2x max for future-proofing

        def _in_range(val: float) -> bool:
            """Sanity-check: reject obviously wrong values (e.g. pip counts, member counts)."""
            return _price_lo <= val <= _price_hi

        # Accept 'SL 4550' and 'TP 4536' on separate lines
        for line in combined_text.splitlines():
            line_u = line.upper()
            if not stop_loss:
                m = SL_PATTERN.search(line_u)
                if m:
                    try:
                        sl_candidate = float(m.group(1))
                        # Only accept SL within expected price range
                        if _in_range(sl_candidate):
                            stop_loss = sl_candidate
                    except Exception:
                        pass
            tps = TP_PATTERN.findall(line_u)
            for tp in tps:
                try:
                    tp_val = float(tp)
                    # Only accept TP within expected price range
                    if _in_range(tp_val) and tp_val not in take_profits:
                        take_profits.append(tp_val)
                except Exception:
                    pass

        # Try multi-target pattern: "Target- 4514, 4520, 4530"
        if not take_profits:
            tm = _TARGET_MULTI_RE.search(combined_text)
            if tm:
                raw_nums = re.findall(r"\d{3,7}(?:\.\d{1,5})?", tm.group(1))
                for rn in raw_nums:
                    try:
                        tv = float(rn)
                        if _in_range(tv) and tv not in take_profits:
                            take_profits.append(tv)
                    except Exception:
                        pass

        # If still missing TPs, fallback to price pattern (with range filter)
        if not take_profits:
            numbers = [float(value) for value in PRICE_PATTERN.findall(upper_text)]
            protected = {value for value in [entry_price, entry_range_low, entry_range_high, stop_loss] if value is not None}
            take_profits = [
                value for value in numbers
                if value not in protected and _in_range(value)
            ][1:3]

        # Infer limit order type when entry range detected with a known side
        if entry_range_low is not None and order_type == "MARKET":
            if side == "BUY":
                order_type = "BUY_LIMIT"
            elif side == "SELL":
                order_type = "SELL_LIMIT"

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

        # Cap confidence when all levels come from cluster context with no message-own prices
        _clean_msg = _CLUSTER_BLOCK_RE.sub("", combined_text)
        _msg_has_prices = bool(re.search(r"\d{3,6}", _clean_msg))
        _cluster_injected = ctx and (ctx.get("sl") or ctx.get("entry") or ctx.get("tps"))
        _cluster_only = _cluster_injected and not _msg_has_prices

        fields_found = sum(
            1
            for item in [symbol, side, order_type, entry_price, stop_loss, take_profits[0] if take_profits else None]
            if item not in (None, "")
        )
        confidence = min(0.35 if _cluster_only else 0.95, 0.25 + fields_found * 0.12)
        notes: list[str] = []
        if entry_range_low and entry_range_high:
            notes.append(f"Entry range detected: {entry_range_low}-{entry_range_high}, midpoint={entry_price}")
        if message.image_path:
            notes.append("Image attached; heuristic parser may need AI vision for full accuracy")
        if ctx:
            notes.append("Cluster context applied: " + "; ".join(f"{k}={v}" for k, v in ctx.items() if v))
        if _cluster_only:
            notes.append("WARN: message has no price numbers — cluster-context levels capped to low confidence")

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
        # CRITICAL: reject pure-number tokens (e.g. "4292") that are prices, not symbols
        match = re.search(r"\b([A-Z0-9]{3,10}(?:\d+|USD|EUR|JPY|GBP|AUD|CAD|NZD|CHF|XAU|XAG))\b", upper_text)
        if match:
            candidate = match.group(1)
            # Reject if token is purely numeric (a price misdetected as symbol)
            if candidate.isdigit():
                return None
            return candidate
        return None

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