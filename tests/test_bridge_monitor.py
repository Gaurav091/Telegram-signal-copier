from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("bridge_monitor", ROOT / "tools" / "bridge_monitor.py")
bridge_monitor = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(bridge_monitor)


class DetectSuspiciousBridgeClosesTests(unittest.TestCase):
    def test_detects_market_trade_closed_without_bridge_close_command(self) -> None:
        mql5_lines = [
            "QF      0       10:32:29.783    TelegramSignalCopierEA (XAUUSDm,M1)     TelegramSignalCopierEA result request=add4e0fb-beba-49ca-8260-55c4a005a52b status=FILLED ticket=2869034401 message=done at 4526.912",
        ]
        terminal_lines = [
            "CN      0       10:32:29.766    Trades  '272489632': deal #2869034401 sell 0.01 XAUUSDm at 4526.912 done (based on order #3159141982)",
            "KS      0       10:32:30.410    Trades  '272489632': market buy 0.01 XAUUSDm, close #3159141982 sell 0.01 XAUUSDm 4526.912",
        ]

        suspicious = bridge_monitor._detect_suspicious_bridge_closes(mql5_lines, terminal_lines)

        self.assertEqual(len(suspicious), 1)
        self.assertEqual(suspicious[0]["order_ticket"], 3159141982)
        self.assertEqual(suspicious[0]["bridge_ticket"], 2869034401)
        self.assertAlmostEqual(suspicious[0]["elapsed_seconds"], 0.644, places=3)

    def test_detects_pending_trade_closed_after_fill(self) -> None:
        mql5_lines = [
            "KS      0       09:51:23.746    TelegramSignalCopierEA (XAUUSDm,M1)     TelegramSignalCopierEA result request=191da980-7f82-4ad6-99d3-9edd6fa502ee status=FILLED ticket=3159010750 message=done",
        ]
        terminal_lines = [
            "KP      0       10:11:07.839    Trades  '272489632': deal #2868982680 buy 0.01 XAUUSDm at 4526.000 done (based on order #3159010750)",
            "FR      0       10:11:11.510    Trades  '272489632': market sell 0.01 XAUUSDm, close #3159010750 buy 0.01 XAUUSDm 4526.000",
        ]

        suspicious = bridge_monitor._detect_suspicious_bridge_closes(mql5_lines, terminal_lines)

        self.assertEqual(len(suspicious), 1)
        self.assertEqual(suspicious[0]["order_ticket"], 3159010750)
        self.assertEqual(suspicious[0]["bridge_ticket"], 3159010750)
        self.assertAlmostEqual(suspicious[0]["elapsed_seconds"], 3.671, places=3)

    def test_ignores_close_when_bridge_close_command_is_logged(self) -> None:
        mql5_lines = [
            "QF      0       10:32:29.783    TelegramSignalCopierEA (XAUUSDm,M1)     TelegramSignalCopierEA result request=add4e0fb-beba-49ca-8260-55c4a005a52b status=FILLED ticket=2869034401 message=done at 4526.912",
            "AB      0       10:32:30.000    TelegramSignalCopierEA (XAUUSDm,M1)     TelegramSignalCopierEA executing request=close-1 symbol=XAUUSDm action=CLOSE_FULL order_type=MARKET volume=0.01",
        ]
        terminal_lines = [
            "CN      0       10:32:29.766    Trades  '272489632': deal #2869034401 sell 0.01 XAUUSDm at 4526.912 done (based on order #3159141982)",
            "KS      0       10:32:30.410    Trades  '272489632': market buy 0.01 XAUUSDm, close #3159141982 sell 0.01 XAUUSDm 4526.912",
        ]

        suspicious = bridge_monitor._detect_suspicious_bridge_closes(mql5_lines, terminal_lines)

        self.assertEqual(suspicious, [])


if __name__ == "__main__":
    unittest.main()