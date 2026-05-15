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
    if signal.side is None:
        reasons.append(RejectionReason.MISSING_SIDE)
    if signal.stop_loss is None:
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

    min_rr: float = float(
        os.getenv("AGENT_MIN_RR") or app_config.minimum_rr_ratio
    )
    entry_price = signal.entry_price
    sl = signal.stop_loss
    tps = signal.take_profits

    rr = 0.0
    if tps and entry_price is not None:
        rr = _rr_ratio(signal.side, entry_price, sl, tps[0])
        if rr < min_rr:
            reasons.append(f"{RejectionReason.INVALID_RR}: {rr:.2f} < {min_rr:.2f}")
            logger.warning("[VALIDATE] REJECTED R:R %.2f below minimum %.2f", rr, min_rr)
            return {"rejection_reasons": reasons, "next_node": "reject"}
    elif not tps:
        logger.info("[VALIDATE] No take-profit levels — proceeding without R:R check")

    min_conf: float = getattr(app_config, "minimum_confidence", 0.0)
    if signal.confidence < min_conf:
        reasons.append(
            f"{RejectionReason.LOW_CONFIDENCE}: {signal.confidence:.2f} < {min_conf:.2f}"
        )
        return {"rejection_reasons": reasons, "next_node": "reject"}

    fp = _fingerprint(broker_symbol, signal.side.value, entry_price, sl)
    if fp in _SEEN_FINGERPRINTS:
        reasons.append(RejectionReason.DUPLICATE)
        logger.warning("[VALIDATE] REJECTED duplicate signal fingerprint")
        return {"rejection_reasons": reasons, "next_node": "reject"}
    _SEEN_FINGERPRINTS.add(fp)

    volume = getattr(app_config, "default_volume", 0.01)
    validated = ValidatedSignal(
        symbol=broker_symbol,
        side=signal.side,
        order_type=signal.order_type,
        entry_price=entry_price,
        stop_loss=sl,
        take_profits=tps,
        volume=volume,
        risk_reward_ratio=round(rr, 2),
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