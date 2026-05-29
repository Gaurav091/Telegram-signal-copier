from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from telegram_signal_copier.adapters.bridge import FileBridgeExecutor
from telegram_signal_copier.models import TradeCommand


class FileBridgeExecutorTests(unittest.TestCase):
    def _make_executor(self, root: Path) -> FileBridgeExecutor:
        return FileBridgeExecutor(
            inbox_dir=root / "inbox",
            outbox_dir=root / "outbox",
            timeout_seconds=2.0,
        )

    def _make_command(self, request_id: str, order_type: str) -> TradeCommand:
        return TradeCommand(
            request_id=request_id,
            source_group="test",
            message_id="1",
            symbol="XAUUSD",
            action="SELL",
            order_type=order_type,
            volume=0.10,
            entry_price=4581.0 if order_type != "MARKET" else None,
            stop_loss=4590.0,
            take_profit=4573.0,
            take_profit_targets=[4573.0, 4568.0, 4555.0],
        )

    def test_pending_order_filled_without_price_is_normalized_to_pending(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            executor = self._make_executor(root)
            command = self._make_command("req-pending-1", "SELL_LIMIT")
            outbox = root / "outbox"
            outbox.mkdir(parents=True, exist_ok=True)
            (outbox / "req-pending-1.result").write_text(
                "\n".join(
                    [
                        "request_id=req-pending-1",
                        "status=FILLED",
                        "message=done",
                        "ticket=3168710474",
                        "executed_at=2026-05-25 17:11:13",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            result = executor.submit(command)

            self.assertEqual(result.status, "PENDING")
            self.assertEqual(result.ticket, "3168710474")
            self.assertIsNone(result.executed_price)

    def test_pending_order_with_executed_price_stays_filled(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            executor = self._make_executor(root)
            command = self._make_command("req-pending-2", "SELL_LIMIT")
            outbox = root / "outbox"
            outbox.mkdir(parents=True, exist_ok=True)
            (outbox / "req-pending-2.result").write_text(
                "\n".join(
                    [
                        "request_id=req-pending-2",
                        "status=FILLED",
                        "message=filled",
                        "ticket=3001",
                        "executed_price=4580.5",
                        "executed_at=2026-05-25 17:11:13",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            result = executor.submit(command)

            self.assertEqual(result.status, "FILLED")
            self.assertEqual(result.executed_price, 4580.5)

    def test_modify_filled_without_price_stays_filled(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            executor = self._make_executor(root)
            command = TradeCommand(
                request_id="req-modify-1",
                source_group="test",
                message_id="2",
                symbol="XAUUSD",
                action="MODIFY",
                order_type="",
                volume=0.0,
                entry_price=None,
                stop_loss=None,
                take_profit=None,
                take_profit_targets=[],
                ticket=123456,
                new_sl=4588.0,
            )
            outbox = root / "outbox"
            outbox.mkdir(parents=True, exist_ok=True)
            (outbox / "req-modify-1.result").write_text(
                "\n".join(
                    [
                        "request_id=req-modify-1",
                        "status=FILLED",
                        "message=modified",
                        "ticket=123456",
                        "executed_at=2026-05-25 17:11:13",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            result = executor.submit(command)

            self.assertEqual(result.status, "FILLED")
            self.assertEqual(result.ticket, "123456")


if __name__ == "__main__":
    unittest.main()
