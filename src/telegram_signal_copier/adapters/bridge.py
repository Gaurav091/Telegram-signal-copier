from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from time import monotonic, sleep

from telegram_signal_copier.models import ExecutionResult, TradeCommand


@dataclass(slots=True)
class FileBridgeExecutor:
    inbox_dir: Path
    outbox_dir: Path

    def submit(self, command: TradeCommand, wait_for_result: bool = True, timeout_seconds: float = 30.0) -> ExecutionResult:
        self.inbox_dir.mkdir(parents=True, exist_ok=True)
        self.outbox_dir.mkdir(parents=True, exist_ok=True)

        command_path = self.inbox_dir / f"{command.request_id}.cmd"
        command_path.write_text(command.to_bridge_file(), encoding="utf-8")

        if not wait_for_result:
            return ExecutionResult(
                request_id=command.request_id,
                status="SUBMITTED",
                message="Command written to MT5 bridge inbox",
            )

        result_path = self.outbox_dir / f"{command.request_id}.result"
        deadline = monotonic() + timeout_seconds
        while monotonic() < deadline:
            if result_path.exists():
                lines = result_path.read_text(encoding="utf-8").splitlines()
                return ExecutionResult.from_bridge_lines(lines)
            sleep(0.5)

        return ExecutionResult(
            request_id=command.request_id,
            status="TIMEOUT",
            message="MT5 EA did not return a result before timeout",
        )