from __future__ import annotations

from dataclasses import dataclass, field

from telegram_signal_copier.config import AppConfig
import logging
from telegram_signal_copier.models import ParsedSignal


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

    def evaluate(self, signal: ParsedSignal) -> ValidationDecision:
        reasons: list[str] = []
        if not signal.symbol:
            reasons.append("Missing symbol")
        if not signal.side:
            reasons.append("Missing side")
        merged = list(self.config.merged_allowed_symbols or [])
        allowed_bases = {self._strip_broker_suffix(s) for s in merged}
        sig = signal.symbol.strip().upper() if signal.symbol else ""
        sig_base = self._strip_broker_suffix(sig)
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
        if signal.stop_loss is None:
            reasons.append("Missing stop loss")
        if not signal.take_profits:
            reasons.append("Missing take profit")
        if signal.confidence < self.config.minimum_confidence:
            reasons.append(f"Confidence {signal.confidence:.2f} below minimum {self.config.minimum_confidence:.2f}")

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