"""Pipeline core — orchestrates the message → parse → validate → execute flow."""
from __future__ import annotations

import logging
from dataclasses import asdict, dataclass
from typing import Optional

from telegram_signal_copier.adapters.bridge import FileBridgeExecutor
from telegram_signal_copier.config import AppConfig
from telegram_signal_copier.models import ExecutionResult, ParsedSignal, TelegramSignalMessage, TradeCommand
from telegram_signal_copier.services.image_processor import ImageProcessor, ImageProcessingResult
from telegram_signal_copier.services.intent_classifier import (
    IntentClassifier,
    IntentResult,
    INFO_INTENTS,
    UPDATE_INTENTS,
    INFO_SKIP_THRESHOLD,
    UPDATE_SKIP_THRESHOLD,
)
from telegram_signal_copier.services.pipeline_intent import classify_message_intent
from telegram_signal_copier.services.pipeline_logger import PipelineLogger
from telegram_signal_copier.services.risk_engine import RiskEngine, ValidationDecision
from telegram_signal_copier.services.signal_parser import ParseResult, SignalParser

logger = logging.getLogger(__name__)

# Backward-compatible private aliases (keep existing names working)
_UPDATE_INTENTS = UPDATE_INTENTS
_INFO_INTENTS = INFO_INTENTS
_INFO_SKIP_THRESHOLD = INFO_SKIP_THRESHOLD
_UPDATE_SKIP_THRESHOLD = UPDATE_SKIP_THRESHOLD

# Explicit trade-update captions should short-circuit even when an image is attached.
# These are operational follow-ups, not new entries.
# NOTE: kept here as backward-compatible aliases; canonical patterns live in intent_classifier.py
from telegram_signal_copier.services.intent_classifier import (
    NEW_SIGNAL_OVERRIDE as _NEW_SIGNAL_OVERRIDE,
    TRADE_UPDATE_OVERRIDE as _TRADE_UPDATE_OVERRIDE,
)

# Text-only informational messages can be skipped at 0.90 without risking image-backed entries.
# (Values imported from intent_classifier; re-assigned here for backward compat)


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
        pipeline_logger: Optional[PipelineLogger] = None,
    ) -> None:
        self.config = config
        self.image_processor = image_processor
        self.signal_parser = signal_parser
        self.risk_engine = risk_engine
        self.executor = executor
        self._pipeline_logger = pipeline_logger

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
        intent, intent_confidence, reasoning, force_skip_trade_update = classify_message_intent(
            self.signal_parser, message, primary_image, combined_text
        )

        # If image is present, require much higher confidence before skipping.
        # A chart + ambiguous caption must be attempted as a signal.
        has_image = bool(primary_image)

        # Intent classifiers can mislabel clean text signals as informational/update.
        # Build a lightweight heuristic preview before skipping text-only messages.
        heuristic_preview: ParsedSignal | None = None
        heuristic_preview_complete = False

        if not has_image and (intent in _INFO_INTENTS or (intent in _UPDATE_INTENTS and not force_skip_trade_update)):
            heuristic_text = message.raw_text or combined_text
            heuristic_preview = self.signal_parser._heuristic_parse(message, heuristic_text)
            heuristic_preview_complete = bool(
                heuristic_preview.side and (
                    heuristic_preview.entry_price is not None
                    or heuristic_preview.stop_loss is not None
                    or bool(heuristic_preview.take_profits)
                )
            )

        # Drop pure informational messages (no image: 0.92, with image: never auto-skip)
        if (
            intent in _INFO_INTENTS
            and not has_image
            and intent_confidence >= _INFO_SKIP_THRESHOLD
            and not heuristic_preview_complete
        ):
            logger.info("[PIPELINE] SKIPPED — informational text-only message (conf=%.2f)", intent_confidence)
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

        # For TRADE_UPDATE: only skip if no image AND high confidence.
        # With an image present the same message could contain a fresh chart entry,
        # unless the caption itself is an explicit update directive.
        should_skip_trade_update = force_skip_trade_update or (
            not has_image and intent_confidence >= _UPDATE_SKIP_THRESHOLD and not heuristic_preview_complete
        )
        if intent in _UPDATE_INTENTS and should_skip_trade_update:
            logger.info(
                "[PIPELINE] TRADE_UPDATE skipped (conf=%.2f, override=%s) — no new trade; logged for tracking",
                intent_confidence,
                force_skip_trade_update,
            )
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
        if heuristic_preview is not None:
            heuristic = heuristic_preview
            heuristic_complete = heuristic_preview_complete
        else:
            heuristic_text = message.raw_text or combined_text
            heuristic = self.signal_parser._heuristic_parse(message, heuristic_text)
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
                # If parse_signal returned an intent field, adopt it so the
                # separate classify_intent call can be skipped in future messages.
                # (We already ran classify_intent above; use it for logging only.)
                ai_intent = (image_result.ai_payload or {}).get("intent")
                if ai_intent and isinstance(ai_intent, str):
                    ai_intent_norm = ai_intent.upper()
                    if ai_intent_norm != intent and intent != "UNKNOWN":
                        logger.debug(
                            "[INTENT] AI parse intent=%s differs from classify_intent=%s; keeping classify_intent",
                            ai_intent_norm, intent,
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

        if self._pipeline_logger is not None:
            action = (
                execution_result.status if execution_result else
                ("SKIPPED" if decision.status == "SKIPPED" else "REJECTED")
            )
            self._pipeline_logger.log(
                group_id=message.message_id or "",
                channel_id=0,
                message_count=message.grouped_count or 1,
                image_count=len(message.effective_image_paths()),
                intent=intent,
                intent_confidence=intent_confidence,
                intent_reasoning=reasoning,
                extraction=parse_result.signal if parse_result else None,
                validation=signal if decision.approved else None,
                rejection_reasons=list(decision.reasons) if decision.reasons else [],
                action_taken=action,
                execution_status=execution_result.status if execution_result else None,
                order_ticket=getattr(execution_result, "ticket", None) if execution_result else None,
                execution_error=(
                    execution_result.message
                    if execution_result and execution_result.status not in {"FILLED", "SUBMITTED", "PENDING", "DRY_RUN", "REVIEW"}
                    else None
                ),
                source_group=message.source_group or "",
                message_id=str(message.message_id or ""),
                raw_text_snippet=(message.combined_text() or "")[:200],
            )

        return PipelineOutcome(parse_result=parse_result, decision=decision, execution_result=execution_result)