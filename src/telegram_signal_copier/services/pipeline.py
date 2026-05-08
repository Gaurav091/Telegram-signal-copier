from __future__ import annotations

import logging
from dataclasses import asdict, dataclass

from telegram_signal_copier.adapters.bridge import FileBridgeExecutor
from telegram_signal_copier.config import AppConfig
from telegram_signal_copier.models import ExecutionResult, TelegramSignalMessage, TradeCommand
from telegram_signal_copier.services.image_processor import ImageProcessor, ImageProcessingResult
from telegram_signal_copier.services.risk_engine import RiskEngine, ValidationDecision
from telegram_signal_copier.services.signal_parser import ParseResult, SignalParser

logger = logging.getLogger(__name__)

# Intent values from classify_intent that should NOT trigger a new trade
_UPDATE_INTENTS = {"TRADE_UPDATE"}
_INFO_INTENTS = {"INFORMATIONAL"}
_TRADEABLE_INTENTS = {"NEW_TRADE_SIGNAL", "CHART_ANALYSIS", "UNKNOWN"}


@dataclass(slots=True)
class PipelineOutcome:
    parse_result: ParseResult
    decision: ValidationDecision
    execution_result: ExecutionResult | None

    def to_dict(self) -> dict[str, object]:
        return {
            "parsed_signal": asdict(self.parse_result.signal),
            "used_ai": self.parse_result.used_ai,
            "decision": {"status": self.decision.status, "reasons": self.decision.reasons},
            "execution_result": asdict(self.execution_result) if self.execution_result else None,
        }


class CopierPipeline:
    def __init__(
        self,
        config: AppConfig,
        image_processor: ImageProcessor,
        signal_parser: SignalParser,
        risk_engine: RiskEngine,
        executor: FileBridgeExecutor,
    ) -> None:
        self.config = config
        self.image_processor = image_processor
        self.signal_parser = signal_parser
        self.risk_engine = risk_engine
        self.executor = executor

    def process_message(self, message: TelegramSignalMessage) -> PipelineOutcome:
        images = message.effective_image_paths()
        primary_image = images[0] if images else None
        extra_images = images[1:] if len(images) > 1 else None
        combined_text = message.combined_text()

        logger.info(
            "[PIPELINE] source=%s msg_id=%s grouped=%d text_len=%d images=%d",
            message.source_group,
            message.message_id,
            message.grouped_count,
            len(combined_text),
            len(images),
        )

        # ── Stage 1: Intent Classification ──────────────────────────────────────────
        intent = "UNKNOWN"
        intent_confidence = 0.0
        reasoning = ""
        if self.signal_parser.ai_client:
            try:
                intent_result = self.signal_parser.ai_client.classify_intent(
                    raw_text=combined_text,
                    image_path=primary_image,
                )
                intent = str(intent_result.get("intent", "UNKNOWN")).upper()
                intent_confidence = float(intent_result.get("confidence", 0.0))
                reasoning = intent_result.get("reasoning", "")
                logger.info(
                    "[INTENT] %s (conf=%.2f) — %s",
                    intent,
                    intent_confidence,
                    reasoning,
                )
            except Exception as exc:
                logger.warning("[INTENT] classification failed: %s — treating as UNKNOWN", exc)

        # Drop pure informational messages immediately
        if intent in _INFO_INTENTS and intent_confidence >= 0.80:
            logger.info("[PIPELINE] SKIPPED — informational message (conf=%.2f)", intent_confidence)
            from telegram_signal_copier.models import ParsedSignal
            dummy = ParsedSignal(
                source_group=message.source_group,
                message_id=message.message_id,
                symbol=None,
                side=None,
                notes=[f"Skipped: informational message ({reasoning or intent})"],
            )
            return PipelineOutcome(
                parse_result=ParseResult(signal=dummy, used_ai=bool(self.signal_parser.ai_client)),
                decision=ValidationDecision(status="SKIPPED", reasons=["Informational message"]),
                execution_result=None,
            )

        # For TRADE_UPDATE, log it but don't execute (TradeTracker would handle modify/close in future)
        if intent in _UPDATE_INTENTS and intent_confidence >= 0.75:
            logger.info(
                "[PIPELINE] TRADE_UPDATE detected (conf=%.2f) — no new trade; logged for tracking",
                intent_confidence,
            )
            from telegram_signal_copier.models import ParsedSignal
            dummy = ParsedSignal(
                source_group=message.source_group,
                message_id=message.message_id,
                symbol=None,
                side=None,
                notes=[f"Trade update message (not a new entry): {combined_text[:120]}"],
            )
            return PipelineOutcome(
                parse_result=ParseResult(signal=dummy, used_ai=bool(self.signal_parser.ai_client)),
                decision=ValidationDecision(status="SKIPPED", reasons=["Trade update — not a new entry"]),
                execution_result=None,
            )

        # ── Stage 2: Heuristic fast-path ────────────────────────────────────────────
        heuristic = self.signal_parser._heuristic_parse(message, combined_text)
        heuristic_complete = bool(
            heuristic.side and (
                heuristic.entry_price is not None
                or heuristic.stop_loss is not None
                or bool(heuristic.take_profits)
            )
        )

        if heuristic_complete and not primary_image:
            # Pure-text signal fully parsed — no AI needed
            logger.info(
                "[HEURISTIC] Complete: side=%s entry=%s SL=%s TP=%s",
                heuristic.side,
                heuristic.entry_price,
                heuristic.stop_loss,
                heuristic.take_profits,
            )
            parse_result = ParseResult(signal=heuristic, used_ai=False)
            image_result = ImageProcessingResult(extracted_text="", notes=[])
        else:
            # If source is configured for heuristic-only, skip AI/image processing
            if self.config.is_source_heuristic_only(message.source_group):
                logger.info("[HEURISTIC-ONLY] source %s — skipping AI", message.source_group)
                parse_result = ParseResult(signal=heuristic, used_ai=False)
                image_result = ImageProcessingResult(extracted_text="", notes=["Source configured for heuristic-only parsing"])
            else:
                # ── Stage 3: Image Analysis ──────────────────────────────────────────
                image_result = self.image_processor.extract_signal_context(
                    primary_image,
                    existing_text=combined_text,
                    all_image_paths=extra_images,
                )
                # ── Stage 4: Full AI Parse ───────────────────────────────────────────
                parse_result = self.signal_parser.parse(
                    message,
                    image_text=image_result.extracted_text,
                    image_ai_payload=image_result.ai_payload,
                )
            parse_result.signal.notes.extend(image_result.notes)

        signal = parse_result.signal
        logger.info(
            "[PARSED] symbol=%s side=%s entry=%s SL=%s TP=%s conf=%.2f used_ai=%s",
            signal.symbol,
            signal.side,
            signal.entry_price,
            signal.stop_loss,
            signal.take_profits,
            signal.confidence,
            parse_result.used_ai,
        )

        # ── Stage 5: Risk Validation ─────────────────────────────────────────────────
        decision = self.risk_engine.evaluate(signal)
        logger.info(
            "[DECISION] %s — %s",
            decision.status,
            "; ".join(decision.reasons) if decision.reasons else "OK",
        )

        # ── Stage 6: Execution ───────────────────────────────────────────────────────
        execution_result: ExecutionResult | None = None
        if decision.approved:
            if self.config.dry_run:
                execution_result = ExecutionResult(
                    request_id="dry-run",
                    status="DRY_RUN",
                    message="Dry run enabled, no command sent to MT5 bridge",
                )
                logger.info("[EXECUTION] DRY_RUN — %s %s @ %s", signal.side, signal.symbol, signal.entry_price)
            else:
                command = TradeCommand.from_signal(signal, volume=self.config.default_volume)
                execution_result = self.executor.submit(command)
                logger.info(
                    "[EXECUTION] %s — ticket=%s price=%s",
                    execution_result.status,
                    execution_result.ticket,
                    execution_result.executed_price,
                )
        elif decision.requires_review:
            execution_result = ExecutionResult(
                request_id="review",
                status="REVIEW",
                message="Signal passed parser but requires manual approval",
            )
            logger.info("[EXECUTION] REVIEW required")

        return PipelineOutcome(parse_result=parse_result, decision=decision, execution_result=execution_result)