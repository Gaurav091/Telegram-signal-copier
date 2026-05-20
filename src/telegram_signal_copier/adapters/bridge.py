from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
from time import monotonic, sleep
from contextlib import suppress
from uuid import uuid4

from telegram_signal_copier.models import ExecutionResult, TradeCommand


@dataclass(slots=True)
class FileBridgeExecutor:
    inbox_dir: Path
    outbox_dir: Path
    timeout_seconds: float = 60.0
    symbol_suffix: str = ""
    legacy_inbox_mirror_delay_seconds: float = 2.0

    def _bridge_root(self) -> Path:
        bridge_root = self.inbox_dir
        try:
            if bridge_root.name.lower() == "inbox":
                return bridge_root.parent
        except Exception:
            pass
        return bridge_root

    def _common_files_root(self) -> Path:
        bridge_root = self._bridge_root()
        if bridge_root.parent.name.lower() == "files":
            return bridge_root.parent
        return bridge_root

    def _top_level_command_path(self, request_id: str) -> Path:
        bridge_root = self._bridge_root()
        common_files_root = self._common_files_root()
        if common_files_root == bridge_root:
            return bridge_root / f"{request_id}.txt"
        return common_files_root / f"{bridge_root.name}__{request_id}.txt"

    @staticmethod
    def _append_queue_entry(queue_path: Path, request_id: str) -> None:
        try:
            with queue_path.open("a", encoding="mbcs") as handle:
                handle.write(f"{request_id}\n")
            return
        except Exception:
            pass

        try:
            with queue_path.open("a", encoding="utf-8") as handle:
                handle.write(f"{request_id}\n")
        except Exception:
            # Queue append is best-effort; the direct command files remain as a fallback.
            pass

    @staticmethod
    def _write_command_file(command_path: Path, text: str) -> None:
        tmp_path = command_path.with_suffix(command_path.suffix + ".tmp")
        try:
            # Use Windows ANSI encoding (mbcs) so MQL FILE_ANSI readers can open reliably.
            tmp_path.write_text(text, encoding="mbcs")
            tmp_path.replace(command_path)
        except Exception:
            # Fallback to utf-8 if mbcs not supported or replace fails.
            try:
                tmp_path.write_text(text, encoding="utf-8")
                tmp_path.replace(command_path)
            except Exception:
                # Last resort: write directly without temp file.
                command_path.write_text(text, encoding="utf-8")

    def _payload_text(self, payload: dict[str, str]) -> str:
        return "\n".join(f"{k}={v}" for k, v in payload.items()) + "\n"

    @staticmethod
    def _strip_symbol_suffix(symbol: str) -> str:
        value = symbol.strip()
        upper = value.upper()
        for suffix in (".M", "-M", "M"):
            if upper.endswith(suffix) and len(value) > len(suffix):
                return value[: -len(suffix)]
        return value

    @staticmethod
    def _should_retry_symbol_selection(result: ExecutionResult) -> bool:
        if result.status != "ERROR":
            return False
        msg = (result.message or "").lower()
        return ("select symbol" in msg) or ("symbol" in msg and "not found" in msg)

    def _symbol_retry_candidates(self, symbol: str) -> list[str]:
        if not symbol:
            return []

        base = self._strip_symbol_suffix(symbol).upper()
        aliases: dict[str, list[str]] = {
            "NAS100": ["NAS100", "USTEC", "NQ100", "US100"],
            "US30": ["US30", "DJ30", "WS30"],
            "DJ30": ["DJ30", "US30", "WS30"],
            "SPX500": ["SPX500", "US500", "SP500"],
        }
        base_candidates = aliases.get(base, [base])
        if base not in base_candidates:
            base_candidates = [base, *base_candidates]

        suffixes = [""]
        configured_suffix = str(self.symbol_suffix or "").strip()
        if configured_suffix:
            suffixes.append(configured_suffix)
        for suffix in ("m", ".m", "-m"):
            if suffix not in suffixes:
                suffixes.append(suffix)

        seen: set[str] = set()
        candidates: list[str] = []
        for base_symbol in base_candidates:
            for suffix in suffixes:
                candidate = f"{base_symbol}{suffix}" if suffix else base_symbol
                key = candidate.upper()
                if key in seen:
                    continue
                seen.add(key)
                candidates.append(candidate)
        return candidates

    def submit(
        self,
        command: TradeCommand,
        wait_for_result: bool = True,
        timeout_seconds: float | None = None,
        _allow_symbol_retry: bool = True,
    ) -> ExecutionResult:
        # Normalize bridge root: if caller passed a path that points to
        # an "inbox" subdirectory (common when users set MT5_BRIDGE_DIR
        # incorrectly), prefer the parent bridge root.
        bridge_root = self._bridge_root()
        legacy_inbox_dir = bridge_root / "inbox"

        bridge_root.mkdir(parents=True, exist_ok=True)
        legacy_inbox_dir.mkdir(parents=True, exist_ok=True)
        self.outbox_dir.mkdir(parents=True, exist_ok=True)

        # If there are any existing .cmd files placed in an "inbox"
        # subdirectory, keep them in place. Some deployed EA builds still
        # scan inbox/*.cmd instead of the bridge root.
        try:
            if self.inbox_dir.exists() and self.inbox_dir != bridge_root and self.inbox_dir != legacy_inbox_dir:
                for f in self.inbox_dir.glob("*.cmd"):
                    try:
                        dest = legacy_inbox_dir / f.name
                        if not dest.exists():
                            f.replace(dest)
                    except Exception:
                        pass
        except Exception:
            pass

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

        command_path = bridge_root / f"{command.request_id}.cmd"
        legacy_command_path = legacy_inbox_dir / command_path.name
        top_level_command_path = self._top_level_command_path(command.request_id)
        queue_path = bridge_root / "command_queue.txt"
        # write payload as key=value lines atomically using a temp file
        text = self._payload_text(payload)
        self._write_command_file(command_path, text)
        if top_level_command_path != command_path:
            self._write_command_file(top_level_command_path, text)
        self._append_queue_entry(queue_path, command.request_id)

        if not wait_for_result:
            return ExecutionResult(
                request_id=command.request_id,
                status="SUBMITTED",
                message="Command written to MT5 bridge",
            )

        result_path = self.outbox_dir / f"{command.request_id}.result"
        use_timeout = timeout_seconds if timeout_seconds is not None else self.timeout_seconds
        deadline = monotonic() + float(use_timeout)
        mirror_deadline = monotonic() + max(0.0, float(self.legacy_inbox_mirror_delay_seconds))
        mirrored_to_legacy_inbox = False
        while monotonic() < deadline:
            if result_path.exists():
                lines = result_path.read_text(encoding="utf-8").splitlines()
                result = ExecutionResult.from_bridge_lines(lines)

                with suppress(FileNotFoundError):
                    command_path.unlink()
                with suppress(FileNotFoundError):
                    legacy_command_path.unlink()
                if top_level_command_path != command_path:
                    with suppress(FileNotFoundError):
                        top_level_command_path.unlink()

                if _allow_symbol_retry and self._should_retry_symbol_selection(result):
                    submitted_symbol = str(payload.get("symbol", "") or "")
                    for candidate in self._symbol_retry_candidates(submitted_symbol):
                        if candidate.upper() == submitted_symbol.upper():
                            continue
                        retry_command = replace(
                            command,
                            request_id=str(uuid4()),
                            symbol=candidate,
                        )
                        retry_result = self.submit(
                            retry_command,
                            wait_for_result=wait_for_result,
                            timeout_seconds=timeout_seconds,
                            _allow_symbol_retry=False,
                        )
                        if retry_result.status in {"FILLED", "SUBMITTED", "PENDING"}:
                            return retry_result
                return result

            if (
                not mirrored_to_legacy_inbox
                and monotonic() >= mirror_deadline
                and command_path.exists()
            ):
                # Compatibility fallback for deployed EA builds that still
                # scan bridge_root/inbox/*.cmd instead of bridge_root/*.cmd.
                self._write_command_file(legacy_command_path, text)
                mirrored_to_legacy_inbox = True
            sleep(0.5)

        if (
            command_path.exists()
            or legacy_command_path.exists()
            or (top_level_command_path != command_path and top_level_command_path.exists())
        ):
            return ExecutionResult(
                request_id=command.request_id,
                status="NOT_CONSUMED",
                message="Bridge command still pending; MT5 EA likely not attached or not reading the expected bridge location",
            )

        return ExecutionResult(
            request_id=command.request_id,
            status="NO_RESULT",
            message="MT5 EA consumed the command but did not write a result file before timeout",
        )

    # ------------------------------------------------------------------
    # High-level helpers for modify / close operations
    # ------------------------------------------------------------------

    def modify_trade(
        self,
        symbol: str,
        ticket: int,
        new_sl: float | str | None = None,
        new_tp: float | None = None,
        source_group: str = "",
        message_id: str = "",
        wait_for_result: bool = True,
        timeout_seconds: float | None = None,
    ) -> ExecutionResult:
        """Send a MODIFY command to the MT5 EA.

        ``new_sl`` may be a price (float) or the string ``"BREAKEVEN"``.
        """
        cmd = TradeCommand(
            request_id=str(uuid4()),
            source_group=source_group,
            message_id=message_id,
            symbol=symbol,
            action="MODIFY",
            order_type="",
            volume=0.0,
            entry_price=None,
            stop_loss=None,
            take_profit=None,
            take_profit_targets=[],
            ticket=ticket,
            new_sl=new_sl,
            new_tp=new_tp,
        )
        return self.submit(cmd, wait_for_result=wait_for_result, timeout_seconds=timeout_seconds)

    def close_partial(
        self,
        symbol: str,
        ticket: int,
        close_percent: float,
        source_group: str = "",
        message_id: str = "",
        wait_for_result: bool = True,
        timeout_seconds: float | None = None,
    ) -> ExecutionResult:
        """Send a CLOSE_PARTIAL command.  ``close_percent`` must be 0 < x ≤ 100."""
        cmd = TradeCommand(
            request_id=str(uuid4()),
            source_group=source_group,
            message_id=message_id,
            symbol=symbol,
            action="CLOSE_PARTIAL",
            order_type="",
            volume=0.0,
            entry_price=None,
            stop_loss=None,
            take_profit=None,
            take_profit_targets=[],
            ticket=ticket,
            close_percent=close_percent,
        )
        return self.submit(cmd, wait_for_result=wait_for_result, timeout_seconds=timeout_seconds)

    def close_full(
        self,
        symbol: str,
        ticket: int,
        source_group: str = "",
        message_id: str = "",
        wait_for_result: bool = True,
        timeout_seconds: float | None = None,
    ) -> ExecutionResult:
        """Send a CLOSE_FULL command to close the entire position."""
        cmd = TradeCommand(
            request_id=str(uuid4()),
            source_group=source_group,
            message_id=message_id,
            symbol=symbol,
            action="CLOSE_FULL",
            order_type="",
            volume=0.0,
            entry_price=None,
            stop_loss=None,
            take_profit=None,
            take_profit_targets=[],
            ticket=ticket,
        )
        return self.submit(cmd, wait_for_result=wait_for_result, timeout_seconds=timeout_seconds)