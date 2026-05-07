from __future__ import annotations

from dataclasses import dataclass, field

from telegram_signal_copier.config import AppConfig
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

    def evaluate(self, signal: ParsedSignal) -> ValidationDecision:
        reasons: list[str] = []
        if not signal.symbol:
            reasons.append("Missing symbol")
        if not signal.side:
            reasons.append("Missing side")
        if signal.symbol and signal.symbol not in {symbol.upper() for symbol in self.config.allowed_symbols}:
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