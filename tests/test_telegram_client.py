import unittest
from pathlib import Path
from unittest.mock import patch

from telegram_signal_copier.adapters.telegram_client import (
    TelegramSignalListener,
    _patched_platform_uname_for_telethon,
)
from telegram_signal_copier.config import AppConfig


def build_config() -> AppConfig:
    return AppConfig(
        project_root=Path("."),
        bridge_inbox_dir=Path("bridge"),
        bridge_outbox_dir=Path("bridge") / "outbox",
        telegram_api_id="1",
        telegram_api_hash="hash",
        telegram_phone_number="+10000000000",
        telegram_session_name="test-session",
        telegram_sources=["Gold Expertise::1609490547"],
        openai_api_key=None,
        openai_model="gpt-4.1-mini",
        openai_base_url="https://api.openai.com/v1",
        minimum_confidence=0.70,
        default_volume=0.10,
        allowed_symbols=["XAUUSD"],
        dry_run=True,
        approval_required_below=0.85,
        poll_interval_seconds=1.0,
    )


class FakeClient:
    def __init__(self, authorized: bool) -> None:
        self.authorized = authorized
        self.connect_calls = 0
        self.start_calls: list[tuple[str, str]] = []

    async def connect(self) -> None:
        self.connect_calls += 1

    async def is_user_authorized(self) -> bool:
        return self.authorized

    async def start(self, *, phone=None, bot_token=None) -> None:
        if phone is not None:
            self.start_calls.append(("phone", phone))
        if bot_token is not None:
            self.start_calls.append(("bot_token", bot_token))


class TelegramSignalListenerTests(unittest.IsolatedAsyncioTestCase):
    def test_patched_platform_uname_for_telethon_uses_windows_fallback(self) -> None:
        with patch("telegram_signal_copier.adapters.telegram_client.os.name", "nt"), patch(
            "telegram_signal_copier.adapters.telegram_client.platform.uname",
            side_effect=RuntimeError("wmi hang"),
        ):
            with _patched_platform_uname_for_telethon():
                info = __import__("telegram_signal_copier.adapters.telegram_client", fromlist=["platform"]).platform.uname()

            self.assertEqual(info.machine, "AMD64")
            self.assertEqual(info.release, "10")

    async def test_connect_listener_client_uses_existing_authorized_session(self) -> None:
        listener = TelegramSignalListener(build_config())
        client = FakeClient(authorized=True)

        await listener._connect_listener_client(client)

        self.assertEqual(client.connect_calls, 1)
        self.assertEqual(client.start_calls, [])

    async def test_connect_listener_client_rejects_unauthorized_phone_session(self) -> None:
        listener = TelegramSignalListener(build_config())
        client = FakeClient(authorized=False)

        with self.assertRaisesRegex(RuntimeError, "not authorized"):
            await listener._connect_listener_client(client)

        self.assertEqual(client.connect_calls, 1)
        self.assertEqual(client.start_calls, [])

    async def test_connect_listener_client_can_start_bot_session(self) -> None:
        config = build_config()
        config.telegram_phone_number = None
        config.telegram_bot_token = "bot-token"
        listener = TelegramSignalListener(config)
        client = FakeClient(authorized=False)

        await listener._connect_listener_client(client)

        self.assertEqual(client.connect_calls, 1)
        self.assertEqual(client.start_calls, [("bot_token", "bot-token")])


if __name__ == "__main__":
    unittest.main()