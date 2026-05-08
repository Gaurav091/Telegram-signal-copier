from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from time import monotonic, sleep

from telegram_signal_copier.models import ExecutionResult, TradeCommand


@dataclass(slots=True)
class FileBridgeExecutor:
    inbox_dir: Path
    outbox_dir: Path
    timeout_seconds: float = 60.0
    symbol_suffix: str = ""

    def submit(self, command: TradeCommand, wait_for_result: bool = True, timeout_seconds: float | None = None) -> ExecutionResult:
        self.inbox_dir.mkdir(parents=True, exist_ok=True)
        self.outbox_dir.mkdir(parents=True, exist_ok=True)

        # Build payload and apply optional symbol suffix mapping for broker variants
        payload = command.to_bridge_payload()
        if self.symbol_suffix:
            try:
                sym = payload.get("symbol", "") or ""
                if sym:
                    s = str(sym).strip()
                    # append suffix if not already present (case-insensitive)
                    if not s.upper().endswith(self.symbol_suffix.upper()):
                        payload["symbol"] = s + str(self.symbol_suffix)
            except Exception:
                pass

        command_path = self.inbox_dir / f"{command.request_id}.cmd"
        # write payload as key=value lines
        command_path.write_text("\n".join(f"{k}={v}" for k, v in payload.items()) + "\n", encoding="utf-8")

        if not wait_for_result:
            return ExecutionResult(
                request_id=command.request_id,
                status="SUBMITTED",
                message="Command written to MT5 bridge inbox",
            )

        result_path = self.outbox_dir / f"{command.request_id}.result"
        use_timeout = timeout_seconds if timeout_seconds is not None else self.timeout_seconds
        deadline = monotonic() + float(use_timeout)
        while monotonic() < deadline:
            if result_path.exists():
                lines = result_path.read_text(encoding="utf-8").splitlines()
                return ExecutionResult.from_bridge_lines(lines)
            sleep(0.5)

        if command_path.exists():
            return ExecutionResult(
                request_id=command.request_id,
                status="NOT_CONSUMED",
                message="Bridge command still in inbox; MT5 EA likely not attached or not reading the common bridge folder",
            )

        return ExecutionResult(
            request_id=command.request_id,
            status="NO_RESULT",
            message="MT5 EA consumed the command but did not write a result file before timeout",
        )