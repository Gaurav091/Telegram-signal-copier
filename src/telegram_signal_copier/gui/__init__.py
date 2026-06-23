"""GUI subpackage — Flet-based dashboard for Telegram Signal Copier."""
from telegram_signal_copier.config import AppConfig as AppConfig  # noqa: F401
from telegram_signal_copier.gui.dashboard import SignalCopierDashboard as SignalCopierDashboard  # noqa: F401
from telegram_signal_copier.services.settings_manager import SettingsManager as SettingsManager  # noqa: F401

# Backward-compatibility for unit tests that patch telegram_signal_copier.gui.subprocess
from telegram_signal_copier.gui import dashboard as _dashboard_mod  # noqa: F401
subprocess = _dashboard_mod.subprocess  # type: ignore[attr-defined]  # noqa: F401
