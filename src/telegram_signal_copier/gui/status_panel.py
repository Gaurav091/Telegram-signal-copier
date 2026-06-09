"""Status panel — right sidebar with connection status, metrics, lot sizing."""
from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any

import flet as ft

from telegram_signal_copier.config import AppConfig
from telegram_signal_copier.gui.theme import (
    BADGE_BG,
    BG_PANEL,
    BORDER,
    ERROR,
    INPUT_BORDER,
    PRIMARY,
    SECONDARY,
    SURFACE,
    TEXT_PRIMARY,
    TEXT_SECONDARY,
)
from telegram_signal_copier.services.settings_manager import SettingsManager

logger = logging.getLogger(__name__)


class StatusPanel:
    """Right sidebar: connection status, metrics, lot sizing, TP strategy."""

    def __init__(self, page: ft.Page, settings_manager: SettingsManager) -> None:
        self.page = page
        self.settings_manager = settings_manager

        # Status indicators
        self.tg_status_icon = ft.Icon(ft.Icons.CIRCLE, color=ERROR, size=9)
        self.tg_status_text = ft.Text("Disconnected", size=12, weight=ft.FontWeight.W_500)
        self.mt5_status_icon = ft.Icon(ft.Icons.CIRCLE, color=ERROR, size=9)
        self.mt5_status_text = ft.Text("Waiting", size=12, weight=ft.FontWeight.W_500)

        # Metrics
        self.metric_active_channels = ft.Text("0", size=14, color=PRIMARY, weight=ft.FontWeight.BOLD)
        self.metric_signals = ft.Text("0", size=14, color=PRIMARY, weight=ft.FontWeight.BOLD)
        self.metric_total_trades = ft.Text("0", size=14, color=PRIMARY, weight=ft.FontWeight.BOLD)
        self.metric_success_rate = ft.Text("0%", size=14, color=SECONDARY, weight=ft.FontWeight.BOLD)

        # Lot sizing controls
        self.lot_mode_dropdown = ft.Dropdown(
            options=[ft.dropdown.Option("Fixed Lot"), ft.dropdown.Option("Risk %")],
            value="Fixed Lot",
            height=32,
            text_size=11,
            border_color=INPUT_BORDER,
            content_padding=ft.Padding.symmetric(horizontal=8, vertical=4),
        )
        self.quick_lot_input = ft.TextField(
            value=str(settings_manager.get("default_volume", "0.01")),
            height=32,
            width=70,
            text_size=11,
            content_padding=ft.Padding.symmetric(horizontal=8, vertical=4),
            border_color=INPUT_BORDER,
        )

        # TP strategy
        self.tp_strategy_dropdown = ft.Dropdown(
            options=[
                ft.dropdown.Option("Split TP"),
                ft.dropdown.Option("Trail Stop"),
                ft.dropdown.Option("TP1 Only"),
            ],
            value="Split TP",
            height=32,
            text_size=11,
            border_color=INPUT_BORDER,
            content_padding=ft.Padding.symmetric(horizontal=8, vertical=4),
        )

        self.right_container = self._build_right_sidebar()

    def _build_right_sidebar(self) -> ft.Container:
        return ft.Container(
            content=ft.Column(
                [
                    ft.Text("STATUS", size=11, color=TEXT_SECONDARY, weight=ft.FontWeight.W_600),
                    ft.Container(
                        content=ft.Column(
                            [
                                ft.Row([self.tg_status_icon, ft.Text("Telegram:", size=11), self.tg_status_text], spacing=4),
                                ft.Row([self.mt5_status_icon, ft.Text("MT5:", size=11), self.mt5_status_text], spacing=4),
                            ],
                            spacing=6,
                        ),
                        bgcolor=SURFACE,
                        padding=ft.Padding.symmetric(horizontal=10, vertical=8),
                        border_radius=6,
                        border=ft.Border.all(1, BORDER),
                    ),
                    ft.Text("METRICS", size=11, color=TEXT_SECONDARY, weight=ft.FontWeight.W_600),
                    ft.Container(
                        content=ft.Column(
                            [
                                ft.Row([ft.Text("Channels:", size=11), self.metric_active_channels], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                                ft.Row([ft.Text("Signals:", size=11), self.metric_signals], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                                ft.Row([ft.Text("Trades:", size=11), self.metric_total_trades], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                                ft.Row([ft.Text("Win Rate:", size=11), self.metric_success_rate], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                            ],
                            spacing=4,
                        ),
                        bgcolor=SURFACE,
                        padding=ft.Padding.symmetric(horizontal=10, vertical=8),
                        border_radius=6,
                        border=ft.Border.all(1, BORDER),
                    ),
                    ft.Text("LOT SIZING", size=11, color=TEXT_SECONDARY, weight=ft.FontWeight.W_600),
                    ft.Container(
                        content=ft.Column(
                            [
                                ft.Row([ft.Text("Mode:", size=11), self.lot_mode_dropdown], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                                ft.Row([ft.Text("Lots:", size=11), self.quick_lot_input], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                                ft.ElevatedButton(
                                    "Save",
                                    height=28,
                                    color=TEXT_PRIMARY,
                                    bgcolor="#26262b",
                                    style=ft.ButtonStyle(shape=ft.RoundedRectangleBorder(radius=4), text_style=ft.TextStyle(size=11)),
                                    on_click=self.on_save_quick_lot,
                                ),
                            ],
                            spacing=6,
                        ),
                        bgcolor=SURFACE,
                        padding=ft.Padding.symmetric(horizontal=10, vertical=8),
                        border_radius=6,
                        border=ft.Border.all(1, BORDER),
                    ),
                    ft.Text("TP STRATEGY", size=11, color=TEXT_SECONDARY, weight=ft.FontWeight.W_600),
                    ft.Container(
                        content=ft.Column([self.tp_strategy_dropdown], spacing=6),
                        bgcolor=SURFACE,
                        padding=ft.Padding.symmetric(horizontal=10, vertical=8),
                        border_radius=6,
                        border=ft.Border.all(1, BORDER),
                    ),
                ],
                spacing=10,
                scroll=ft.ScrollMode.AUTO,
            ),
            width=200,
            bgcolor=BG_PANEL,
            padding=ft.Padding.only(left=12, right=12, top=15, bottom=15),
            border=ft.Border.only(left=ft.BorderSide(1, BORDER)),
        )

    # ── Public API ─────────────────────────────────────────────────────────

    def poll_connection_status(self, listener_process: Any, config: AppConfig) -> None:
        """Check Telethon session and MT5 bridge status files."""
        tg_connected = False
        mt5_connected = False

        bridge_root = config.bridge_inbox_dir
        if bridge_root.name.lower() == "inbox":
            bridge_root = bridge_root.parent

        status_file = bridge_root / "telegram_status.txt"
        ea_status_file = bridge_root / "ea_status.txt"

        if status_file.exists():
            try:
                for line in status_file.read_text(encoding="utf-8").splitlines():
                    if "=" in line:
                        k, v = line.split("=", 1)
                        if k.strip() == "telegram_connected" and v.strip() in {"1", "true", "True"}:
                            tg_connected = True
                        elif k.strip() == "listener_state" and v.strip() in {"running", "connected"}:
                            tg_connected = True
            except Exception:
                pass

        if ea_status_file.exists():
            try:
                for line in ea_status_file.read_text(encoding="utf-8").splitlines():
                    if "=" in line:
                        k, v = line.split("=", 1)
                        if k.strip() == "heartbeat_epoch":
                            hb = int(v.strip())
                            if hb > 0 and abs(int(time.time()) - hb) < 20:
                                mt5_connected = True
            except Exception:
                pass

        is_running = listener_process is not None and listener_process.poll() is None

        if tg_connected or is_running:
            self.tg_status_icon.color = SECONDARY
            self.tg_status_text.value = "Connected (Running)"
        else:
            self.tg_status_icon.color = ERROR
            self.tg_status_text.value = "Disconnected"

        if mt5_connected:
            self.mt5_status_icon.color = SECONDARY
            self.mt5_status_text.value = "Connected (EA Listening)"
        else:
            self.mt5_status_icon.color = ERROR
            self.mt5_status_text.value = "Waiting (No Terminal)"

    def update_metrics(self, trades: list[dict[str, Any]], active_channels: int) -> None:
        """Update metric displays from trade data."""
        total = len(trades)
        wins = losses = closed = 0

        for t in trades:
            profit = self._safe_float(t.get("profit", ""))
            status = t.get("status", "PENDING")
            is_closed = status in {"FILLED", "CLOSED", "TP_HIT", "SL_HIT"} or profit != 0.0
            if is_closed:
                closed += 1
                if profit > 0:
                    wins += 1
                elif profit < 0:
                    losses += 1

        self.metric_active_channels.value = str(active_channels)
        self.metric_total_trades.value = str(total)
        self.metric_signals.value = str(total)

        if closed > 0:
            rate = int((wins / closed) * 100)
            self.metric_success_rate.value = f"{rate}%"
            self.metric_success_rate.color = SECONDARY if rate >= 50 else "#ff9100" if rate >= 30 else ERROR
        else:
            self.metric_success_rate.value = "N/A"
            self.metric_success_rate.color = TEXT_SECONDARY

    # ── Event handlers ─────────────────────────────────────────────────────

    def on_save_quick_lot(self, e: Any = None) -> None:
        try:
            val = float(self.quick_lot_input.value)
            self.settings_manager.set("default_volume", val)
            self.page.show_dialog(ft.SnackBar(content=ft.Text(f"Quick lot size set to {val}!")))
        except ValueError:
            self.page.show_dialog(ft.SnackBar(content=ft.Text("Invalid lot size! Must be a float number.")))

    @staticmethod
    def _safe_float(val: str) -> float:
        try:
            return float(val) if val else 0.0
        except (ValueError, TypeError):
            return 0.0
