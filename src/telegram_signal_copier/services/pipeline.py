from __future__ import annotations

from dataclasses import asdict, dataclass

from telegram_signal_copier.adapters.bridge import FileBridgeExecutor
from telegram_signal_copier.config import AppConfig
from telegram_signal_copier.models import ExecutionResult, TelegramSignalMessage, TradeCommand
from telegram_signal_copier.services.image_processor import ImageProcessor, ImageProcessingResult
from telegram_signal_copier.services.risk_engine import RiskEngine, ValidationDecision
from telegram_signal_copier.services.signal_parser import ParseResult, SignalParser


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
        # Heuristic-first: avoid AI calls when heuristic already extracted clear fields
        combined_text = message.combined_text()
        heuristic = self.signal_parser._heuristic_parse(message, combined_text)
        heuristic_complete = bool(
            heuristic.side and (
                heuristic.entry_price is not None or heuristic.stop_loss is not None or bool(heuristic.take_profits)
            )
        )

        if heuristic_complete:
            parse_result = ParseResult(signal=heuristic, used_ai=False)
            image_result = ImageProcessingResult(extracted_text="", notes=[])
        else:
            image_result = self.image_processor.extract_signal_context(message.image_path, existing_text=combined_text)
            parse_result = self.signal_parser.parse(message, image_text=image_result.extracted_text)
            parse_result.signal.notes.extend(image_result.notes)

        decision = self.risk_engine.evaluate(parse_result.signal)
        execution_result: ExecutionResult | None = None
        if decision.approved:
            if self.config.dry_run:
                execution_result = ExecutionResult(
                    request_id="dry-run",
                    status="DRY_RUN",
                    message="Dry run enabled, no command sent to MT5 bridge",
                )
            else:
                command = TradeCommand.from_signal(parse_result.signal, volume=self.config.default_volume)
                execution_result = self.executor.submit(command)
        elif decision.requires_review:
            execution_result = ExecutionResult(
                request_id="review",
                status="REVIEW",
                message="Signal passed parser but requires manual approval",
            )

        return PipelineOutcome(parse_result=parse_result, decision=decision, execution_result=execution_result)