"""Dashboard orchestrator — assembles panels, wires events, runs poller."""
from __future__ import annotations

import asyncio
import logging
import subprocess
import sys
from typing import Any

import flet as ft

from telegram_signal_copier.config import AppConfig
from telegram_signal_copier.config_helpers import _default_project_root
from telegram_signal_copier.gui.channels_panel import ChannelsPanel
from telegram_signal_copier.gui.dialogs import show_add_channel_dialog, show_settings_dialog
from telegram_signal_copier.gui.status_panel import StatusPanel
from telegram_signal_copier.gui.theme import (
    BADGE_BG,
    BG_PANEL,
    BORDER,
    ERROR,
    PRIMARY,
    SECONDARY,
    TEXT_PRIMARY,
    setup_page_properties,
)
from telegram_signal_copier.gui.trades_panel import TradesPanel
from telegram_signal_copier.services.settings_manager import SettingsManager

logger = logging.getLogger(__name__)


class SignalCopierDashboard:
    def __init__(self, page: ft.Page) -> None:
        self.page = page
        self.project_root = _default_project_root().expanduser()
        self.settings_manager = SettingsManager(self.project_root)
        self.config = AppConfig.from_env(self.project_root)

        # Auto-detect MT5 terminal path (find where TelegramSignalCopierEA.ex5 lives)
        import os
        from pathlib import Path
        
        # Find the terminal that contains our EA
        mt5_data_root = Path(os.environ.get('APPDATA')) / 'MetaQuotes' / 'Terminal'
        detected_path = None
        
        if mt5_data_root.exists():
            for terminal_folder in mt5_data_root.iterdir():
                if terminal_folder.is_dir() and terminal_folder.name not in ['Common', 'Community', 'Help']:
                    experts_dir = terminal_folder / 'MQL5' / 'Experts'
                    if experts_dir.exists():
                        # Check if our EA is here
                        ea_file = experts_dir / 'TelegramSignalCopierEA.ex5'
                        if ea_file.exists():
                            detected_path = str(terminal_folder)
                            logger.info(f"Found EA in terminal: {detected_path}")
                            break
        
        # Fallback: use any terminal with Experts folder
        if not detected_path and mt5_data_root.exists():
            for terminal_folder in mt5_data_root.iterdir():
                if terminal_folder.is_dir() and terminal_folder.name not in ['Common', 'Community', 'Help']:
                    experts_dir = terminal_folder / 'MQL5' / 'Experts'
                    if experts_dir.exists():
                        detected_path = str(terminal_folder)
                        logger.info(f"Using fallback terminal: {detected_path}")
                        break
        
        if detected_path:
            os.environ["MT5_DATA_PATH"] = detected_path
            if hasattr(self.config, 'mt5_data_path'):
                self.config.mt5_data_path = detected_path
            elif hasattr(self.config, 'mt5_terminal_path'):
                self.config.mt5_terminal_path = detected_path
            logger.info(f"Set MT5 data path to: {detected_path}")
        else:
            logger.warning("Could not auto-detect MT5 terminal path")

        # Background process tracker
        self.listener_process: subprocess.Popen | None = None
        self.is_listener_running = False

        # Build panels
        self.trades_panel = TradesPanel(page, self.config)
        self.channels_panel = ChannelsPanel(page)
        self.status_panel = StatusPanel(page, self.settings_manager)

        # Wire channel panel callbacks
        self.channels_panel.on_add_channel_requested = self._on_add_channel_dialog

        setup_page_properties(page)
        self.build_ui()

        # Seed demo trades only if no real bridge data
        bridge_dir = self.config.bridge_inbox_dir
        has_real_data = False
        if bridge_dir.exists():
            outbox = bridge_dir / "outbox"
            if outbox.exists() and any(outbox.glob("*.result")):
                has_real_data = True
            elif any(f for f in bridge_dir.glob("*.txt") if f.name not in {"command_queue.txt", "telegram_sources.txt", "telegram_status.txt"}):
                has_real_data = True
        if not has_real_data:
            self.trades_panel.seed_demo_trades()

        self.start_status_poller()

    def build_ui(self) -> None:
        # Header
        self.start_stop_button = ft.TextButton(
            "START LISTENER",
            style=ft.ButtonStyle(color=SECONDARY),
            on_click=self.on_start_listener,
        )
        header = ft.Container(
            content=ft.Row(
                [
                    ft.Row(
                        [
                            ft.Icon(ft.Icons.SHIELD, color=PRIMARY, size=28),
                            ft.Text("TRADECOPIER", size=20, weight=ft.FontWeight.BOLD, color=TEXT_PRIMARY),
                            ft.Container(
                                content=ft.Text("v1.2", size=10, color=PRIMARY),
                                bgcolor=BADGE_BG,
                                padding=ft.Padding.symmetric(horizontal=6, vertical=2),
                                border_radius=4,
                            ),
                        ],
                        alignment=ft.MainAxisAlignment.START,
                        spacing=8,
                    ),
                    ft.Row(
                        [
                            ft.IconButton(icon=ft.Icons.PLAY_ARROW, icon_color=SECONDARY, icon_size=28, tooltip="Start Listener Daemon", on_click=self.on_start_listener),
                            self.start_stop_button,
                            ft.IconButton(icon=ft.Icons.SETTINGS, icon_color=TEXT_PRIMARY, tooltip="Open Settings", on_click=self._on_open_settings),
                        ],
                        spacing=10,
                    ),
                ],
                alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
            ),
            padding=ft.Padding.only(left=20, right=20, top=15, bottom=15),
            bgcolor=BG_PANEL,
            border=ft.Border.only(bottom=ft.BorderSide(1, BORDER)),
        )

        # Assemble layout
        self.page.add(
            ft.Column(
                [
                    header,
                    ft.Row(
                        [
                            self.channels_panel.sidebar_container,
                            self.trades_panel.center_area,
                            self.status_panel.right_container,
                        ],
                        expand=True,
                        spacing=0,
                    ),
                ],
                expand=True,
                spacing=0,
            )
        )
        self._refresh_channels()

    # ── Polling ────────────────────────────────────────────────────────────

    def start_status_poller(self) -> None:
        async def poll_state() -> None:
            while True:
                try:
                    self.status_panel.poll_connection_status(self.listener_process, self.config)
                    self._poll_bridge_trades()
                except Exception as exc:
                    logger.debug("GUI poller error: %s", exc)
                await asyncio.sleep(2.0)

        self.page.run_task(poll_state)

    def _poll_bridge_trades(self) -> None:
        """Parse MT5 File Bridge directory for trade logs."""
        bridge_dir = self.config.bridge_inbox_dir
        if not bridge_dir.exists():
            return

        trades = []
        for item in bridge_dir.glob("*.txt"):
            if item.name in {"command_queue.txt", "telegram_sources.txt", "telegram_status.txt"}:
                continue
            try:
                cmd_data = {}
                for line in item.read_text(encoding="utf-8").splitlines():
                    if "=" in line:
                        k, v = line.split("=", 1)
                        cmd_data[k.strip()] = v.strip()
                req_id = cmd_data.get("request_id")
                if not req_id:
                    continue
                res_data = {}
                res_file = bridge_dir / "outbox" / f"{req_id}.result"
                if res_file.exists():
                    for line in res_file.read_text(encoding="utf-8").splitlines():
                        if "=" in line:
                            k, v = line.split("=", 1)
                            res_data[k.strip()] = v.strip()
                trades.append({
                    "time": cmd_data.get("submitted_epoch", "0"),
                    "source_group": cmd_data.get("source_group", ""),
                    "symbol": cmd_data.get("symbol", ""),
                    "action": cmd_data.get("action", ""),
                    "volume": cmd_data.get("volume", ""),
                    "sl": cmd_data.get("stop_loss", ""),
                    "tp": cmd_data.get("take_profit", ""),
                    "status": res_data.get("status", "PENDING"),
                    "message": res_data.get("message", ""),
                    "profit": res_data.get("profit", ""),
                    "entry_price": res_data.get("price", cmd_data.get("price", "")),
                })
            except Exception:
                continue

        trades.sort(key=lambda x: x.get("time", "0"), reverse=True)
        if trades:
            self.trades_panel.active_trades = trades

        display = self.trades_panel.active_trades
        self.trades_panel.populate_trades(display)
        self.trades_panel.update_performance_chart(display)
        self.status_panel.update_metrics(display, len(self.config.telegram_source_mappings))
        self.page.update()

    # ── Event handlers ─────────────────────────────────────────────────────

    def _refresh_channels(self) -> None:
        self.config = AppConfig.from_env(self.project_root)
        self.channels_panel.refresh_channels_list(self.config, self.settings_manager)

    # ── Backward-compatible public aliases expected by tests ─────────────
    # tests/test_gui_dialog.py calls these older method names directly.
    def on_add_channel_dialog(self, e: Any = None) -> None:
        _ = e
        self._on_add_channel_dialog()

    def on_search_channels(self, e: Any = None) -> None:
        _ = e
        self._on_add_channel_dialog()

    def on_open_settings(self, e: Any = None) -> None:
        self._on_open_settings(e)

    def on_clear_trades(self, e: Any = None) -> None:
        _ = e
        # Backward compatibility: older tests call this handler expecting it
        # to exist; TradesPanel implements on_clear_trades (not clear_trades).
        if hasattr(self.trades_panel, "on_clear_trades"):
            self.trades_panel.on_clear_trades()
        elif hasattr(self.trades_panel, "clear_trades"):
            self.trades_panel.clear_trades()  # type: ignore[attr-defined]
        self.page.update()

    def on_quick_lot_mode_change(self, e: Any = None) -> None:
        _ = e
        if hasattr(self.trades_panel, "on_quick_lot_mode_change"):
            self.trades_panel.on_quick_lot_mode_change()  # type: ignore[attr-defined]
        elif hasattr(self.trades_panel, "quick_lot_mode_change"):
            self.trades_panel.quick_lot_mode_change()  # type: ignore[attr-defined]
        self.page.update()

    def on_save_quick_lot(self, e: Any = None) -> None:
        _ = e
        if hasattr(self.trades_panel, "on_save_quick_lot"):
            self.trades_panel.on_save_quick_lot()  # type: ignore[attr-defined]
        elif hasattr(self.trades_panel, "save_quick_lot"):
            self.trades_panel.save_quick_lot()  # type: ignore[attr-defined]
        self.page.update()

    # ── Current internal handlers ───────────────────────────────────────────
    def _on_add_channel_dialog(self) -> None:
        show_add_channel_dialog(self.page, self.config, self.settings_manager, self._refresh_channels)

    def _on_open_settings(self, e: Any = None) -> None:
        show_settings_dialog(self.page, self.settings_manager, self._refresh_channels)

    def on_start_listener(self, e: Any = None) -> None:
        if self.is_listener_running:
            if self.listener_process is not None:
                try:
                    self.listener_process.terminate()
                    self.listener_process.wait(timeout=3)
                except Exception:
                    try:
                        self.listener_process.kill()
                    except Exception:
                        pass
                self.listener_process = None
            # Close log file handle
            log_fh = getattr(self, "_listener_log_fh", None)
            if log_fh and not log_fh.closed:
                try:
                    log_fh.close()
                except Exception:
                    pass
                self._listener_log_fh = None
            self.is_listener_running = False
            self.start_stop_button.content = "START LISTENER"
            self.start_stop_button.style = ft.ButtonStyle(color=SECONDARY)
        else:
            # Clean up stale lock/pid files from crashed instances
            runtime_dir = self.project_root / "runtime"
            for stale in ("listener.lock", "listener.pid"):
                try:
                    (runtime_dir / stale).unlink(missing_ok=True)
                except Exception:
                    pass
            py_exe = sys.executable
            args = [py_exe, "listen"] if getattr(sys, "frozen", False) else [py_exe, "-m", "telegram_signal_copier.main", "listen"]
            log_path = self.project_root / "logs" / "gui_listener.log"
            try:
                log_path.parent.mkdir(parents=True, exist_ok=True)
                log_fh = open(log_path, "w", encoding="utf-8")
                self.listener_process = subprocess.Popen(args, cwd=str(self.project_root), stdout=log_fh, stderr=subprocess.STDOUT)
                self._listener_log_fh = log_fh
                self.is_listener_running = True
                self.start_stop_button.content = "STOP LISTENER"
                self.start_stop_button.style = ft.ButtonStyle(color=ERROR)
            except Exception as exc:
                self.page.show_dialog(ft.SnackBar(content=ft.Text(f"Failed to start listener: {exc}")))
        self.page.update()
