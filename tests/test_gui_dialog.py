"""Unit tests for SignalCopierDashboard settings dialog and event handlers."""
import unittest
from typing import Any
from unittest.mock import MagicMock, patch

import flet as ft


def _make_dashboard() -> "SignalCopierDashboard":
    """Create a dashboard instance with mocked Flet page and dependencies."""
    from telegram_signal_copier.gui import SignalCopierDashboard

    mock_page = MagicMock(spec=ft.Page)
    mock_page.title = ""
    mock_page.theme_mode = None
    mock_page.bgcolor = None
    mock_page.padding = 0
    mock_page.window = MagicMock()
    mock_page.theme = None
    mock_page.add = MagicMock()
    mock_page.update = MagicMock()
    mock_page.run_task = MagicMock()
    mock_page.show_dialog = MagicMock()
    mock_page.pop_dialog = MagicMock()

    with patch(
        "telegram_signal_copier.gui.SettingsManager"
    ) as MockSettings, patch(
        "telegram_signal_copier.gui.AppConfig"
    ) as MockConfig:
        settings_inst = MockSettings.return_value
        settings_inst.get = MagicMock(
            side_effect=lambda key, default=None: default
        )
        settings_inst.set = MagicMock()

        config_inst = MockConfig.from_env.return_value
        config_inst.telegram_source_mappings = []
        config_inst.bridge_inbox_dir = MagicMock()
        config_inst.bridge_inbox_dir.name = "inbox"
        config_inst.bridge_inbox_dir.parent = MagicMock()
        config_inst.bridge_inbox_dir.parent.__truediv__ = MagicMock(
            return_value=MagicMock(exists=MagicMock(return_value=False))
        )

        dashboard = SignalCopierDashboard(mock_page)

    return dashboard


class TestOnOpenSettings(unittest.TestCase):
    """Tests for the on_open_settings method."""

    def setUp(self) -> None:
        self.dashboard = _make_dashboard()

    def test_on_open_settings_accepts_none(self) -> None:
        """on_open_settings should accept None as the event parameter."""
        self.dashboard.on_open_settings(None)
        self.dashboard.page.show_dialog.assert_called()

    def test_on_open_settings_accepts_any_object(self) -> None:
        """on_open_settings should accept any object as the event parameter."""
        dummy = object()
        self.dashboard.on_open_settings(dummy)
        self.dashboard.page.show_dialog.assert_called()

    def test_on_open_settings_no_args(self) -> None:
        """on_open_settings should work when called with no arguments."""
        self.dashboard.on_open_settings()
        self.dashboard.page.show_dialog.assert_called()

    def test_on_open_settings_shows_dialog(self) -> None:
        """on_open_settings should show an AlertDialog."""
        self.dashboard.on_open_settings()
        call_args = self.dashboard.page.show_dialog.call_args
        dialog = call_args[0][0]
        self.assertIsInstance(dialog, ft.AlertDialog)

    def test_on_open_settings_dialog_has_tabs(self) -> None:
        """The settings dialog should contain a Tabs widget."""
        self.dashboard.on_open_settings()
        call_args = self.dashboard.page.show_dialog.call_args
        dialog = call_args[0][0]
        content = dialog.content.content
        self.assertIsInstance(content, ft.Tabs)


class TestUnusedEventHandlerParams(unittest.TestCase):
    """Tests that event handlers with unused `e` params accept Any."""

    def setUp(self) -> None:
        self.dashboard = _make_dashboard()

    def test_on_search_channels_accepts_none(self) -> None:
        self.dashboard.on_search_channels(None)

    def test_on_quick_lot_mode_change_accepts_none(self) -> None:
        self.dashboard.on_quick_lot_mode_change(None)

    def test_on_save_quick_lot_accepts_none(self) -> None:
        self.dashboard.on_save_quick_lot(None)

    def test_on_clear_trades_accepts_none(self) -> None:
        self.dashboard.on_clear_trades(None)


class TestOnStartListener(unittest.TestCase):
    """Tests for on_start_listener with mocked subprocess."""

    def setUp(self) -> None:
        self.dashboard = _make_dashboard()

    @patch("telegram_signal_copier.gui.subprocess.Popen")
    def test_start_listener_spawns_process(self, mock_popen: MagicMock) -> None:
        """Starting the listener should spawn a subprocess."""
        self.dashboard.on_start_listener(None)
        mock_popen.assert_called_once()
        self.assertTrue(self.dashboard.is_listener_running)
        self.assertEqual(self.dashboard.start_stop_button.content, "STOP LISTENER")

    @patch("telegram_signal_copier.gui.subprocess.Popen")
    def test_start_listener_then_stop(self, mock_popen: MagicMock) -> None:
        """Starting then stopping the listener should terminate the process."""
        mock_proc = MagicMock()
        mock_proc.poll.return_value = None
        mock_popen.return_value = mock_proc

        self.dashboard.on_start_listener(None)
        self.assertTrue(self.dashboard.is_listener_running)

        self.dashboard.on_start_listener(None)
        self.assertFalse(self.dashboard.is_listener_running)
        mock_proc.terminate.assert_called_once()

    @patch("telegram_signal_copier.gui.subprocess.Popen", side_effect=OSError("no python"))
    def test_start_listener_handles_os_error(self, mock_popen: MagicMock) -> None:
        """Starting the listener with an OS error should not crash."""
        self.dashboard.on_start_listener(None)
        self.assertFalse(self.dashboard.is_listener_running)
        self.dashboard.page.show_dialog.assert_called()


class TestOnAddChannelDialog(unittest.TestCase):
    """Tests for on_add_channel_dialog."""

    def setUp(self) -> None:
        self.dashboard = _make_dashboard()

    def test_opens_dialog(self) -> None:
        """on_add_channel_dialog should show a dialog."""
        self.dashboard.on_add_channel_dialog(None)
        self.dashboard.page.show_dialog.assert_called_once()
        dialog = self.dashboard.page.show_dialog.call_args[0][0]
        self.assertIsInstance(dialog, ft.AlertDialog)

    def test_starts_async_load(self) -> None:
        """on_add_channel_dialog should schedule async dialog loading."""
        self.dashboard.page.run_task.reset_mock()
        self.dashboard.on_add_channel_dialog(None)
        self.dashboard.page.run_task.assert_called()


if __name__ == "__main__":
    unittest.main()
