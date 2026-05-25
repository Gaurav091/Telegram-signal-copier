import unittest
from os import environ
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from telegram_signal_copier.config import AppConfig
import telegram_signal_copier.config as config_module


def build_config() -> AppConfig:
    tmp_path = Path(".")
    return AppConfig(
        project_root=tmp_path,
        bridge_inbox_dir=tmp_path / "inbox",
        bridge_outbox_dir=tmp_path / "outbox",
        telegram_api_id="1",
        telegram_api_hash="hash",
        telegram_phone_number=None,
        telegram_session_name="test-session",
        telegram_sources=[
            "FX VIP CLUB::@fxvipclub",
            "Gold Expertise::1609490547",
            "Star Trading::1610937993",
        ],
        openai_api_key=None,
        openai_model="gpt-4.1-mini",
        openai_base_url="https://api.openai.com/v1",
        minimum_confidence=0.70,
        default_volume=0.10,
        allowed_symbols=["XAUUSD", "EURUSD", "GBPUSD", "USDJPY"],
        dry_run=True,
        approval_required_below=0.85,
        poll_interval_seconds=1.0,
    )


class AppConfigTests(unittest.TestCase):
    def test_labeled_sources_expose_labels_and_identifiers(self) -> None:
        config = build_config()

        self.assertEqual(
            config.telegram_source_mappings,
            [
                ("FX VIP CLUB", "@fxvipclub"),
                ("Gold Expertise", "1609490547"),
                ("Star Trading", "1610937993"),
            ],
        )
        self.assertEqual(
            config.telegram_source_identifiers,
            ["@fxvipclub", "1609490547", "1610937993"],
        )
        self.assertEqual(
            config.telegram_source_labels,
            ["FX VIP CLUB", "Gold Expertise", "Star Trading"],
        )
        self.assertTrue(config.telegram_ready)

    def test_from_env_uses_appdata_home_when_frozen(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            appdata = Path(tmp_dir) / "Roaming"
            with patch.dict(environ, {"APPDATA": str(appdata)}, clear=True):
                with patch.object(config_module.sys, "frozen", True, create=True):
                    with patch.object(config_module.sys, "executable", str(Path(tmp_dir) / "install" / "TelegramSignalCopier.exe")):
                        config = AppConfig.from_env()

            self.assertEqual(config.project_root, appdata / "TelegramSignalCopier")

    def test_from_env_loads_dotenv_from_executable_dir_when_frozen(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            temp_root = Path(tmp_dir)
            appdata = temp_root / "Roaming"
            install_dir = temp_root / "install"
            install_dir.mkdir(parents=True, exist_ok=True)
            (install_dir / ".env").write_text(
                "TELEGRAM_API_ID=123456\nDEFAULT_VOLUME=0.05\n",
                encoding="utf-8",
            )

            with patch.dict(environ, {"APPDATA": str(appdata)}, clear=True):
                with patch.object(config_module.sys, "frozen", True, create=True):
                    with patch.object(config_module.sys, "executable", str(install_dir / "TelegramSignalCopier.exe")):
                        config = AppConfig.from_env()

            self.assertEqual(config.project_root, appdata / "TelegramSignalCopier")
            self.assertEqual(config.telegram_api_id, "123456")
            self.assertEqual(config.default_volume, 0.05)


if __name__ == "__main__":
    unittest.main()