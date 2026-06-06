"""Risk & Validation Agent."""
from __future__ import annotations

import logging
import os
from hashlib import sha256
from typing import Any

from telegram_signal_copier.agents.schemas import (
    AgentState,
    RejectionReason,
    Side,
    ValidatedSignal,
)
from telegram_signal_copier.config import AppConfig

logger = logging.getLogger(__name__)

_SYMBOL_MAP: dict[str, str] = {
    "GOLD": "XAUUSD", "XAU": "XAUUSD",
    "SILVER": "XAGUSD", "XAG": "XAGUSD",
    "US30": "DJ30", "DOW": "DJ30",
    "NAS100": "NAS100", "NASDAQ": "NAS100",
    "SP500": "SPX500", "SPX": "SPX500", "US500": "SPX500",
    "DAX": "GER40", "GER30": "GER40",
    "OIL": "USOIL", "CRUDE": "USOIL", "WTI": "USOIL", "BRENT": "UKOIL",
    "BTC": "BTCUSD", "BITCOIN": "BTCUSD",
    "ETH": "ETHUSD", "ETHEREUM": "ETHUSD",
}


def _canonical_symbol(raw: str | None) -> str | None:
    if not raw:
        return None
    upper = raw.strip().upper()
    for suffix in (".M", "-M", "M", "+", "-"):
        if upper.endswith(suffix) and len(upper) > len(suffix):
            base = upper[: -len(suffix)]
            return _SYMBOL_MAP.get(base, base)
    return _SYMBOL_MAP.get(upper, upper)


def _strip_suffix(symbol: str | None) -> str | None:
    if not symbol:
        return None
    s = symbol.strip().upper()
    for suf in (".M", "-M", "M"):
        if s.endswith(suf) and len(s) > len(suf):
            return s[: -len(suf)]
    return s


def _rr_ratio(side: Side, entry: float, sl: float, tp: float) -> float:
    risk = abs(entry - sl)
    if risk == 0:
        return 0.0
    return abs(tp - entry) / risk


_SEEN_FINGERPRINTS: set[str] = set()

# Plausible price ranges per canonical symbol (base, without broker suffix).
# Signals whose SL *and* TP both fall outside this range are rejected as
# malformed — the LLM likely extracted prices from the wrong context.
# These are wide bounds covering extreme historical moves; update via
# SYMBOL_PRICE_RANGE_<SYMBOL>=min,max env var if needed.
_SYMBOL_PRICE_RANGES: dict[str, tuple[float, float]] = {
    "XAUUSD":  (3000.0,  8000.0),   # Gold — hasn't been below 3000 since early 2025
    "XAGUSD":  (15.0,    150.0),
    "EURUSD":  (0.80,    1.60),
    "GBPUSD":  (1.00,    2.00),
    "USDJPY":  (80.0,    200.0),
    "USDCHF":  (0.70,    1.40),
    "AUDUSD":  (0.50,    1.10),
    "NZDUSD":  (0.40,    1.00),
    "USDCAD":  (0.90,    1.80),
    "BTCUSD":  (5000.0,  250000.0),
    "ETHUSD":  (100.0,   25000.0),
    "USOIL":   (20.0,    200.0),
    "UKOIL":   (20.0,    220.0),
    "DJ30":    (20000.0, 60000.0),
    "NAS100":  (8000.0,  30000.0),
    "SPX500":  (2000.0,  8000.0),
    "GER40":   (10000.0, 25000.0),
}

# Minimum distance (in price units) between entry and SL that the broker
# will accept.  Stops closer than this will be rejected by MT5 with
# "Invalid stops".  Override via SYMBOL_MIN_STOP_<SYMBOL>=N env var.
_SYMBOL_MIN_STOP: dict[str, float] = {
    "XAUUSD":  10.0,
    "XAGUSD":  0.20,
    "BTCUSD":  50.0,
    "ETHUSD":  5.0,
    "NAS100":  5.0,
    "DJ30":    10.0,
    "SPX500":  2.0,
    "GER40":   5.0,
}


def _fingerprint(symbol: str, side: str, entry: float | None, sl: float) -> str:
    key = f"{symbol}|{side}|{entry or ''}|{sl}"
    return sha256(key.encode()).hexdigest()


def validation_agent_node(state: AgentState, app_config: AppConfig) -> dict[str, Any]:
    """LangGraph node: validate and enrich the extracted signal."""
    signal = state.extracted_signal
    if signal is None:
        return {"rejection_reasons": [RejectionReason.MISSING_SYMBOL], "next_node": "reject"}

    reasons: list[str] = []

    if not signal.symbol_raw:
        reasons.append(RejectionReason.MISSING_SYMBOL)
    side = signal.side
    sl = signal.stop_loss
    if side is None:
        reasons.append(RejectionReason.MISSING_SIDE)
    if sl is None:
        reasons.append(RejectionReason.MISSING_SL)

    if reasons:
        logger.warning("[VALIDATE] REJECTED mandatory fields: %s", reasons)
        return {"rejection_reasons": reasons, "next_node": "reject"}

    broker_symbol = _canonical_symbol(signal.symbol_raw)
    if not broker_symbol:
        return {"rejection_reasons": [RejectionReason.MISSING_SYMBOL], "next_node": "reject"}

    allowed: set[str] = set()
    raw_allowed = (
        getattr(app_config, "merged_allowed_symbols", None)
        or getattr(app_config, "allowed_symbols", [])
    )
    for s in raw_allowed:
        base = _strip_suffix(s)
        if base:
            allowed.add(base)

    if allowed:
        base_sym = _strip_suffix(broker_symbol) or broker_symbol
        if base_sym not in allowed:
            if getattr(app_config, "auto_add_new_symbols", False):
                logger.info("[VALIDATE] Symbol %s not in allow-list; auto_add enabled", broker_symbol)
            else:
                reasons.append(f"{RejectionReason.SYMBOL_NOT_ALLOWED}: {broker_symbol}")
                logger.warning("[VALIDATE] REJECTED symbol not allowed: %s", broker_symbol)
                return {"rejection_reasons": reasons, "next_node": "reject"}

    # ── Price-range sanity check ──────────────────────────────────────────
    # Reject signals where ALL price levels are outside the known range for
    # the symbol — this catches LLM extractions from wrong market context
    # (e.g. XAUUSD signal with prices at 2340 when market is at 4540).
    base_sym_for_range = _strip_suffix(broker_symbol) or broker_symbol
    env_range = os.getenv(f"SYMBOL_PRICE_RANGE_{base_sym_for_range}")
    price_range = None
    if env_range:
        try:
            lo, hi = env_range.split(",")
            price_range = (float(lo), float(hi))
        except Exception:
            logger.debug("Invalid SYMBOL_PRICE_RANGE_%s=%r — expected 'lo,hi'", base_sym_for_range, env_range, exc_info=True)
    if price_range is None:
        price_range = _SYMBOL_PRICE_RANGES.get(base_sym_for_range)

    if price_range is not None:
        lo, hi = price_range
        candidate_prices = [
            p for p in [
                signal.entry_price, signal.stop_loss, *(signal.take_profits or [])
            ] if p is not None and p > 0
        ]
        if candidate_prices and all(not (lo <= p <= hi) for p in candidate_prices):
            reasons.append(
                f"{RejectionReason.INVALID_PRICE_RANGE}: prices={candidate_prices[:3]} "
                f"outside {base_sym_for_range} range ({lo}-{hi})"
            )
            logger.warning(
                "[VALIDATE] REJECTED price range: symbol=%s prices=%s range=(%s,%s)",
                broker_symbol, candidate_prices[:3], lo, hi,
            )
            return {"rejection_reasons": reasons, "next_node": "reject"}

    min_rr: float = float(
        os.getenv("AGENT_MIN_RR") or app_config.minimum_rr_ratio
    )
    entry_price = signal.entry_price
    sl = signal.stop_loss
    tps = signal.take_profits

    # ── Minimum stop distance check ──────────────────────────────────────
    # Reject signals where SL is too close to entry for the broker to accept.
    # Uses entry_price if provided, else falls back to checking TP-SL gap.
    env_min_stop = os.getenv(f"SYMBOL_MIN_STOP_{base_sym_for_range}")
    min_stop: float | None = None
    if env_min_stop:
        try:
            min_stop = float(env_min_stop)
        except Exception:
            logger.debug("Invalid SYMBOL_MIN_STOP_%s=%r — expected float", base_sym_for_range, env_min_stop, exc_info=True)
    if min_stop is None:
        min_stop = _SYMBOL_MIN_STOP.get(base_sym_for_range)

    if min_stop is not None and sl is not None:
        if entry_price is not None and entry_price > 0:
            stop_dist = abs(entry_price - sl)
        elif tps:
            stop_dist = abs(tps[0] - sl)   # proxy: TP1-SL as minimum trade range
        else:
            stop_dist = None
        if stop_dist is not None and stop_dist < min_stop:
            reasons.append(
                f"{RejectionReason.STOP_TOO_CLOSE}: stop_dist={stop_dist:.1f} < min={min_stop:.1f}"
            )
            logger.warning(
                "[VALIDATE] REJECTED stop too close: symbol=%s stop_dist=%.1f min=%.1f",
                broker_symbol, stop_dist, min_stop,
            )
            return {"rejection_reasons": reasons, "next_node": "reject"}

    rr = 0.0
    if tps and entry_price is not None and sl is not None and side is not None:
        # For multi-TP signals the trade is NOT forced to close at TP1.
        # Use the best achievable R:R (farthest TP) so that valid multi-TP
        # setups like "TP1 4543 / TP2 4557 / TP3 4570" aren't rejected just
        # because the first partial-profit target is close to entry.
        rr_values = [_rr_ratio(side, entry_price, sl, tp) for tp in tps]
        rr = max(rr_values)                 # best R:R across all targets
        rr_tp1 = rr_values[0]              # kept for logging clarity
        if rr < min_rr:
            reasons.append(f"{RejectionReason.INVALID_RR}: best_rr={rr:.2f} < {min_rr:.2f}")
            logger.warning(
                "[VALIDATE] REJECTED R:R best=%.2f (tp1=%.2f) below minimum %.2f",
                rr, rr_tp1, min_rr,
            )
            return {"rejection_reasons": reasons, "next_node": "reject"}
        logger.debug("[VALIDATE] R:R tp1=%.2f best=%.2f (using best for threshold check)", rr_tp1, rr)
    elif not tps:
        logger.info("[VALIDATE] No take-profit levels — proceeding without R:R check")

    min_conf: float = getattr(app_config, "minimum_confidence", 0.0)
    if signal.confidence < min_conf:
        reasons.append(
            f"{RejectionReason.LOW_CONFIDENCE}: {signal.confidence:.2f} < {min_conf:.2f}"
        )
        return {"rejection_reasons": reasons, "next_node": "reject"}

    if side is not None and sl is not None:
        fp = _fingerprint(broker_symbol, side.value, entry_price, sl)
        if fp in _SEEN_FINGERPRINTS:
            reasons.append(RejectionReason.DUPLICATE)
            logger.warning("[VALIDATE] REJECTED duplicate signal fingerprint")
            return {"rejection_reasons": reasons, "next_node": "reject"}
        _SEEN_FINGERPRINTS.add(fp)

    volume = getattr(app_config, "default_volume", 0.01)
    assert side is not None  # validated earlier
    assert sl is not None  # validated earlier
    validated = ValidatedSignal(
        symbol=broker_symbol,
        side=side,
        order_type=signal.order_type,
        entry_price=entry_price,
        stop_loss=sl,
        take_profits=tps,
        volume=volume,
        risk_reward_ratio=round(rr, 2),  # best R:R across all TPs
        source_group=state.source_group,
        message_id=state.message_id,
        comment=f"TG|{state.source_group[:16]}|{state.message_id[-8:]}",
    )

    logger.info(
        "[VALIDATE] APPROVED symbol=%s side=%s entry=%s sl=%s tps=%s rr=%.2f vol=%.2f",
        validated.symbol, validated.side, validated.entry_price,
        validated.stop_loss, validated.take_profits,
        validated.risk_reward_ratio, validated.volume,
    )

    return {"validated_signal": validated, "next_node": "execute"}