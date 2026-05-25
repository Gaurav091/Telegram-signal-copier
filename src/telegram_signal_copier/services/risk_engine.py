from __future__ import annotations

from dataclasses import dataclass, field
import os

from telegram_signal_copier.config import AppConfig
import logging
from telegram_signal_copier.models import ParsedSignal


_SYMBOL_ALIASES: dict[str, str] = {
    "GOLD": "XAUUSD",
    "XAU": "XAUUSD",
    "SILVER": "XAGUSD",
    "XAG": "XAGUSD",
    "DOW": "US30",
    "DJ30": "US30",
    "DOWJONES": "US30",
    "US500": "SPX500",
    "SP500": "SPX500",
    "SPX": "SPX500",
    "NASDAQ": "NAS100",
    "NDX": "NAS100",
    "NQ": "NAS100",
    "BTC": "BTCUSD",
    "ETH": "ETHUSD",
}

# Wide but realistic ranges to block obvious OCR/AI mis-parses.
_SYMBOL_PRICE_RANGES: dict[str, tuple[float, float]] = {
    "XAUUSD": (3000.0, 8000.0),
    "XAGUSD": (15.0, 150.0),
    "EURUSD": (0.80, 1.60),
    "GBPUSD": (1.00, 2.00),
    "USDJPY": (80.0, 200.0),
    "BTCUSD": (5000.0, 250000.0),
    "ETHUSD": (100.0, 25000.0),
    "USOIL": (20.0, 200.0),
    "US30": (20000.0, 60000.0),
    "NAS100": (8000.0, 30000.0),
    "SPX500": (2000.0, 8000.0),
}

# Minimum broker-safe distance between entry and protective levels.
_SYMBOL_MIN_STOP: dict[str, float] = {
    "XAUUSD": 10.0,
    "XAGUSD": 0.20,
    "BTCUSD": 50.0,
    "ETHUSD": 5.0,
    "NAS100": 5.0,
    "US30": 10.0,
    "SPX500": 2.0,
}

_SYMBOL_MIN_TP1_DISTANCE: dict[str, float] = {
    "XAUUSD": 3.0,
}


@dataclass(slots=True)
class ValidationDecision:
    status: str
    reasons: list[str] = field(default_factory=list)

    @property
    def approved(self) -> bool:
        return self.status == "APPROVED"

    @property
    def rejected(self) -> bool:
        return self.status == "REJECTED"

    @property
    def requires_review(self) -> bool:
        return self.status == "REVIEW"


class RiskEngine:
    def __init__(self, config: AppConfig) -> None:
        self.config = config
        self._seen_signatures: set[str] = set()

    @staticmethod
    def _strip_broker_suffix(symbol: str | None) -> str | None:
        if not symbol:
            return None
        s = str(symbol).strip().upper()
        for suf in ('.M', '-M', 'M'):
            if s.endswith(suf):
                return s[: -len(suf)]
        return s

    @classmethod
    def _canonical_symbol(cls, symbol: str | None) -> str | None:
        if not symbol:
            return None
        base = cls._strip_broker_suffix(symbol)
        if not base:
            return None
        return _SYMBOL_ALIASES.get(base, base)

    @staticmethod
    def _resolve_price_range(symbol_base: str | None) -> tuple[float, float] | None:
        if not symbol_base:
            return None
        env_key = f"SYMBOL_PRICE_RANGE_{symbol_base}"
        env_val = os.getenv(env_key)
        if env_val:
            try:
                lo, hi = env_val.split(",", 1)
                return float(lo), float(hi)
            except Exception:
                pass
        return _SYMBOL_PRICE_RANGES.get(symbol_base)

    @staticmethod
    def _resolve_min_stop(symbol_base: str | None) -> float | None:
        if not symbol_base:
            return None
        env_key = f"SYMBOL_MIN_STOP_{symbol_base}"
        env_val = os.getenv(env_key)
        if env_val:
            try:
                return float(env_val)
            except Exception:
                pass
        return _SYMBOL_MIN_STOP.get(symbol_base)

    @staticmethod
    def _resolve_min_tp1_distance(symbol_base: str | None) -> float | None:
        if not symbol_base:
            return None
        env_key = f"SYMBOL_MIN_TP1_DISTANCE_{symbol_base}"
        env_val = os.getenv(env_key)
        if env_val:
            try:
                return float(env_val)
            except Exception:
                pass
        return _SYMBOL_MIN_TP1_DISTANCE.get(symbol_base)

    def evaluate(self, signal: ParsedSignal) -> ValidationDecision:
        reasons: list[str] = []
        if not signal.symbol:
            reasons.append("Missing symbol")
        if not signal.side:
            reasons.append("Missing side")
        merged = list(self.config.merged_allowed_symbols or [])
        allowed_bases = {
            self._canonical_symbol(s)
            for s in merged
            if self._canonical_symbol(s)
        }
        sig = signal.symbol.strip().upper() if signal.symbol else ""
        sig_base = self._canonical_symbol(sig)
        if sig and sig_base not in allowed_bases:
            # attempt auto-add when enabled (use base symbol without broker suffix)
            if getattr(self.config, "auto_add_new_symbols", False):
                added = self.config.add_dynamic_symbol(sig_base)
                if added:
                    logging.getLogger(__name__).info("Auto-added new symbol: %s", sig_base)
                    allowed_bases.add(sig_base)
                else:
                    reasons.append(f"Symbol {signal.symbol} not allowed")
            else:
                reasons.append(f"Symbol {signal.symbol} not allowed")

        price_range = self._resolve_price_range(sig_base)
        if price_range is not None:
            lo, hi = price_range
            levels = [
                value
                for value in [signal.entry_price, signal.stop_loss, *(signal.take_profits or [])]
                if value is not None and value > 0
            ]
            if levels and all(not (lo <= value <= hi) for value in levels):
                reasons.append(
                    f"Prices {levels[:3]} outside expected range for {sig_base} ({lo}-{hi})"
                )

        if signal.stop_loss is None:
            reasons.append("Missing stop loss")
        if not signal.take_profits:
            reasons.append("Missing take profit")
        if signal.confidence < self.config.minimum_confidence:
            reasons.append(f"Confidence {signal.confidence:.2f} below minimum {self.config.minimum_confidence:.2f}")

        # ── SL / TP direction sanity checks (AGENT_SPEC §11 rules 6 & 7) ────────
        # Only enforceable when entry_price is known (limit/stop orders).
        # Market orders without explicit entry skip the check.
        entry = signal.entry_price
        sl = signal.stop_loss
        side = (signal.side or "").upper()
        tp1 = signal.take_profits[0] if signal.take_profits else None

        if entry is not None and sl is not None and side:
            if side == "BUY" and sl >= entry:
                reasons.append(
                    f"SL {sl} must be BELOW entry {entry} for BUY "
                    f"(inverted SL would cause immediate stop-out)"
                )
            elif side == "SELL" and sl <= entry:
                reasons.append(
                    f"SL {sl} must be ABOVE entry {entry} for SELL "
                    f"(inverted SL would cause immediate stop-out)"
                )

        if entry is not None and tp1 is not None and side:
            if side == "BUY" and tp1 <= entry:
                reasons.append(
                    f"TP1 {tp1} must be ABOVE entry {entry} for BUY"
                )
            elif side == "SELL" and tp1 >= entry:
                reasons.append(
                    f"TP1 {tp1} must be BELOW entry {entry} for SELL"
                )

        if entry is None and sl is not None and tp1 is not None and side:
            if side == "BUY" and tp1 <= sl:
                reasons.append(f"TP1 {tp1} must be ABOVE SL {sl} for BUY when entry is missing")
            elif side == "SELL" and tp1 >= sl:
                reasons.append(f"TP1 {tp1} must be BELOW SL {sl} for SELL when entry is missing")

        min_stop = self._resolve_min_stop(sig_base)
        if (
            min_stop is not None
            and sig_base == "XAUUSD"
            and signal.entry_range_low is not None
            and signal.entry_range_high is not None
        ):
            # Gold entry zones from providers like GTA often use tighter scalp distances than
            # the single-price market-order guard. Keep the stricter default for non-range trades.
            min_stop = min(min_stop, 5.0)
        min_tp1_distance = self._resolve_min_tp1_distance(sig_base)
        if min_tp1_distance is None:
            min_tp1_distance = min_stop

        if min_stop is not None and sl is not None and tp1 is not None:
            if entry is not None and entry > 0:
                sl_dist = abs(entry - sl)
                tp_dist = abs(tp1 - entry)
                if sl_dist < min_stop:
                    reasons.append(
                        f"SL distance {sl_dist:.2f} is too close to entry {entry} for {sig_base} (min {min_stop:.2f})"
                    )
                if min_tp1_distance is not None and tp_dist < min_tp1_distance:
                    reasons.append(
                        f"TP1 distance {tp_dist:.2f} is too close to entry {entry} for {sig_base} (min {min_tp1_distance:.2f})"
                    )
            else:
                # Without entry, a very narrow TP/SL band often becomes invalid stops at execution time.
                band = abs(tp1 - sl)
                if band < (2.0 * min_stop):
                    reasons.append(
                        f"TP/SL band {band:.2f} is too tight for {sig_base} without entry context (min {2.0 * min_stop:.2f})"
                    )

        signature = signal.signature()
        if signature in self._seen_signatures:
            reasons.append("Duplicate signal")

        if reasons:
            return ValidationDecision(status="REJECTED", reasons=reasons)

        self._seen_signatures.add(signature)

        if signal.requires_review:
            return ValidationDecision(
                status="REVIEW",
                reasons=["SL or TP supplemented from chart image — manual review required before execution"],
            )

        if signal.confidence < self.config.approval_required_below:
            return ValidationDecision(status="REVIEW", reasons=["Manual approval threshold triggered"])

        return ValidationDecision(status="APPROVED")