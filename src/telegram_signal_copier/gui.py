"""Flet-based Desktop GUI Dashboard for Telegram Signal Copier.

Provides real-time analytics, settings modification, channel toggles,
and runner process start/stop management.
"""
from __future__ import annotations

import asyncio
import datetime
import logging
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import flet as ft

from telegram_signal_copier.config import AppConfig
from telegram_signal_copier.config_helpers import _default_project_root, _parse_source_spec
from telegram_signal_copier.services.settings_manager import SettingsManager

logger = logging.getLogger(__name__)


class SignalCopierDashboard:
    def __init__(self, page: ft.Page) -> None:
        self.page = page
        self.project_root = _default_project_root().expanduser()
        self.settings_manager = SettingsManager(self.project_root)
        self.config = AppConfig.from_env(self.project_root)
        
        # Background process tracker
        self.listener_process: subprocess.Popen | None = None
        self.is_listener_running = False
        
        # UI State Cache
        self.channels_list: list[dict[str, str]] = []
        self.active_trades: list[dict[str, Any]] = []
        self._all_telegram_dialogs: list[dict[str, Any]] = []
        
        self.setup_page_properties()
        self.build_ui()
        self.start_status_poller()

    def setup_page_properties(self) -> None:
        self.page.title = "✦ Telegram Signal Copier - Dashboard"
        self.page.theme_mode = ft.ThemeMode.DARK
        self.page.bgcolor = "#121214"
        self.page.window.width = 1200
        self.page.window.height = 750
        self.page.window.resizable = True
        self.page.padding = 0
        
        # Custom HSL-inspired visual styling theme
        self.page.theme = ft.Theme(
            color_scheme=ft.ColorScheme(
                primary="#00e5ff",  # Neon Cyan
                secondary="#00e676",  # Mint Green
                surface="#1e1e24",
                error="#ff1744"
            )
        )

    def build_ui(self) -> None:
        self.start_stop_button = ft.TextButton(
            "START LISTENER",
            style=ft.ButtonStyle(color="#00e676"),
            on_click=self.on_start_listener
        )
        self.search_box = ft.TextField(
            hint_text="Search channels...",
            prefix_icon=ft.Icons.SEARCH,
            height=40,
            text_size=13,
            content_padding=10,
            border_color="#36363b",
            on_change=self.on_search_channels
        )

        # 1. Header Row
        self.header = ft.Container(
            content=ft.Row(
                [
                    ft.Row(
                        [
                            ft.Icon(ft.Icons.SHIELD, color="#00e5ff", size=28),
                            ft.Text("TRADECOPIER", size=20, weight=ft.FontWeight.BOLD, color="#ffffff"),
                            ft.Container(
                                content=ft.Text("v1.2", size=10, color="#00e5ff"),
                                bgcolor="#1a3238",
                                padding=ft.Padding.symmetric(horizontal=6, vertical=2),
                                border_radius=4,
                            )
                        ],
                        alignment=ft.MainAxisAlignment.START,
                        spacing=8
                    ),
                    ft.Row(
                        [
                            ft.IconButton(
                                icon=ft.Icons.PLAY_ARROW,
                                icon_color="#00e676",
                                icon_size=28,
                                tooltip="Start Listener Daemon",
                                on_click=self.on_start_listener
                            ),
                            self.start_stop_button,
                            ft.IconButton(
                                icon=ft.Icons.SETTINGS,
                                icon_color="#ffffff",
                                tooltip="Open Settings",
                                on_click=self.on_open_settings
                            ),
                        ],
                        spacing=10
                    )
                ],
                alignment=ft.MainAxisAlignment.SPACE_BETWEEN
            ),
            padding=ft.Padding.only(left=20, right=20, top=15, bottom=15),
            bgcolor="#16161a",
            border=ft.Border.only(bottom=ft.BorderSide(1, "#26262b"))
        )

        # 2. Left sidebar: Channel List Manager
        self.sidebar_channels = ft.Column(spacing=10, scroll=ft.ScrollMode.AUTO)
        self.sidebar_container = ft.Container(
            content=ft.Column(
                [
                    ft.Text("TELEGRAM SOURCES", size=13, color="#7c7c82", weight=ft.FontWeight.W_600),
                    self.search_box,
                    ft.Divider(color="#26262b", height=10),
                    self.sidebar_channels,
                    ft.ElevatedButton(
                        "Add New Channel",
                        icon=ft.Icons.ADD,
                        color="#00e5ff",
                        bgcolor="#1a3238",
                        style=ft.ButtonStyle(shape=ft.RoundedRectangleBorder(radius=6)),
                        on_click=self.on_add_channel_dialog
                    )
                ],
                spacing=12
            ),
            width=280,
            bgcolor="#16161a",
            padding=20,
            border=ft.Border.only(right=ft.BorderSide(1, "#26262b"))
        )

        # 3. Right sidebar: Live Connection Status and lot sizes
        self.tg_status_icon = ft.Icon(ft.Icons.CIRCLE, color="#ff1744", size=10)
        self.tg_status_text = ft.Text("Disconnected", size=13, weight=ft.FontWeight.W_500)
        self.mt5_status_icon = ft.Icon(ft.Icons.CIRCLE, color="#ff1744", size=10)
        self.mt5_status_text = ft.Text("Waiting (No Terminal)", size=13, weight=ft.FontWeight.W_500)
        
        self.metric_active_channels = ft.Text("0", size=16, color="#00e5ff", weight=ft.FontWeight.BOLD)
        self.metric_signals = ft.Text("0", size=16, color="#00e5ff", weight=ft.FontWeight.BOLD)
        self.metric_total_trades = ft.Text("0", size=16, color="#00e5ff", weight=ft.FontWeight.BOLD)
        self.metric_success_rate = ft.Text("0%", size=16, color="#00e676", weight=ft.FontWeight.BOLD)
        
        self.lot_mode_dropdown = ft.Dropdown(
            options=[
                ft.dropdown.Option("Fixed Lot"),
                ft.dropdown.Option("Risk Percentage"),
            ],
            value="Fixed Lot",
            height=35,
            text_size=12,
            border_color="#36363b",
            content_padding=5,
            on_select=self.on_quick_lot_mode_change
        )
        self.quick_lot_input = ft.TextField(
            value="0.01",
            height=35,
            width=80,
            text_size=12,
            content_padding=5,
            border_color="#36363b"
        )
        
        self.tp_strategy_dropdown = ft.Dropdown(
            options=[
                ft.dropdown.Option("Split TP Levels"),
                ft.dropdown.Option("Trail Stop"),
                ft.dropdown.Option("TP1 Only"),
            ],
            value="Split TP Levels",
            height=35,
            text_size=12,
            border_color="#36363b",
            content_padding=5
        )

        self.right_container = ft.Container(
            content=ft.Column(
                [
                    ft.Text("CONNECTION STATUS", size=12, color="#7c7c82", weight=ft.FontWeight.W_600),
                    ft.Container(
                        content=ft.Column(
                            [
                                ft.Row([self.tg_status_icon, ft.Text("Telegram:", size=13), self.tg_status_text]),
                                ft.Row([self.mt5_status_icon, ft.Text("MetaTrader 5:", size=13), self.mt5_status_text]),
                            ],
                            spacing=8
                        ),
                        bgcolor="#1e1e24",
                        padding=12,
                        border_radius=6,
                        border=ft.Border.all(1, "#26262b")
                    ),
                    
                    ft.Text("SESSION METRICS", size=12, color="#7c7c82", weight=ft.FontWeight.W_600),
                    ft.Container(
                        content=ft.Column(
                            [
                                ft.Row([ft.Text("Active Channels:", size=12), self.metric_active_channels], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                                ft.Row([ft.Text("Signals Detected:", size=12), self.metric_signals], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                                ft.Row([ft.Text("Total Trades:", size=12), self.metric_total_trades], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                                ft.Row([ft.Text("Win Rate:", size=12), self.metric_success_rate], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                            ],
                            spacing=6
                        ),
                        bgcolor="#1e1e24",
                        padding=12,
                        border_radius=6,
                        border=ft.Border.all(1, "#26262b")
                    ),
                    
                    ft.Text("LOT SIZING", size=12, color="#7c7c82", weight=ft.FontWeight.W_600),
                    ft.Container(
                        content=ft.Column(
                            [
                                ft.Row([ft.Text("Mode:", size=12), self.lot_mode_dropdown], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                                ft.Row([ft.Text("Lots / %:", size=12), self.quick_lot_input], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                                ft.ElevatedButton(
                                    "Save Quick Sizing",
                                    height=30,
                                    color="#ffffff",
                                    bgcolor="#26262b",
                                    style=ft.ButtonStyle(shape=ft.RoundedRectangleBorder(radius=4)),
                                    on_click=self.on_save_quick_lot
                                )
                            ],
                            spacing=8
                        ),
                        bgcolor="#1e1e24",
                        padding=12,
                        border_radius=6,
                        border=ft.Border.all(1, "#26262b")
                    ),
                    
                    ft.Text("TP MODE STRATEGY", size=12, color="#7c7c82", weight=ft.FontWeight.W_600),
                    ft.Container(
                        content=ft.Column(
                            [
                                self.tp_strategy_dropdown,
                                ft.Text("Configures dynamic SL scaling on partial TPs.", size=10, color="#7c7c82")
                            ],
                            spacing=6
                        ),
                        bgcolor="#1e1e24",
                        padding=12,
                        border_radius=6,
                        border=ft.Border.all(1, "#26262b")
                    )
                ],
                spacing=12,
                scroll=ft.ScrollMode.AUTO
            ),
            width=240,
            bgcolor="#16161a",
            padding=20,
            border=ft.Border.only(left=ft.BorderSide(1, "#26262b"))
        )

        # 4. Central Dashboard Area: Trades list and charts
        self.trades_table = ft.DataTable(
            columns=[
                ft.DataColumn(ft.Text("Time", size=11, color="#7c7c82")),
                ft.DataColumn(ft.Text("Symbol", size=11, color="#7c7c82")),
                ft.DataColumn(ft.Text("Type", size=11, color="#7c7c82")),
                ft.DataColumn(ft.Text("Entry", size=11, color="#7c7c82")),
                ft.DataColumn(ft.Text("SL", size=11, color="#7c7c82")),
                ft.DataColumn(ft.Text("TP", size=11, color="#7c7c82")),
                ft.DataColumn(ft.Text("Status", size=11, color="#7c7c82")),
            ],
            rows=[],
            heading_row_height=30,
            data_row_min_height=32,
            data_row_max_height=36,
            horizontal_margin=10,
            column_spacing=15
        )

        self.chart_container = ft.Container(
            content=ft.Text("Real-time equity/win tracking charts will load here once trades populate.", size=12, color="#7c7c82"),
            alignment=ft.Alignment.CENTER,
            bgcolor="#16161a",
            height=140,
            border_radius=6,
            border=ft.Border.all(1, "#26262b")
        )

        self.center_area = ft.Container(
            content=ft.Column(
                [
                    ft.Row(
                        [
                            ft.Text("ACTIVE COPIED TRADES", size=14, weight=ft.FontWeight.BOLD, color="#ffffff"),
                            ft.TextButton(
                                "Clear Table",
                                icon=ft.Icons.DELETE_SWEEP,
                                style=ft.ButtonStyle(color="#ff1744"),
                                on_click=self.on_clear_trades
                            )
                        ],
                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN
                    ),
                    ft.Container(
                        content=ft.Column([self.trades_table], scroll=ft.ScrollMode.ALWAYS),
                        expand=True,
                        bgcolor="#16161a",
                        border_radius=6,
                        border=ft.Border.all(1, "#26262b"),
                        padding=10
                    ),
                    ft.Text("PROFIT PERFORMANCE GROWTH", size=13, weight=ft.FontWeight.W_600, color="#ffffff"),
                    self.chart_container
                ],
                spacing=10,
                expand=True
            ),
            expand=True,
            padding=20
        )

        # Main Layout Assemble
        self.page.add(
            ft.Column(
                [
                    self.header,
                    ft.Row(
                        [
                            self.sidebar_container,
                            self.center_area,
                            self.right_container
                        ],
                        expand=True,
                        spacing=0
                    )
                ],
                expand=True,
                spacing=0
            )
        )

        self.refresh_channels_list()

    # --- Data & UI Refresh Handlers ---

    def refresh_channels_list(self) -> None:
        """Reload channels configuration to GUI sidebar."""
        self.sidebar_channels.controls.clear()
        
        # Load sources from config
        self.config = AppConfig.from_env(self.project_root)
        sources = self.config.telegram_source_mappings
        self.metric_active_channels.value = str(len(sources))
        search_query = self.search_box.value.lower() if self.search_box.value else ""
        disabled_sources = self.settings_manager.get("disabled_sources", [])
        for label, identifier in sources:
            if search_query and (search_query not in label.lower() and search_query not in identifier.lower()):
                continue
                
            self.sidebar_channels.controls.append(
                ft.Container(
                    content=ft.Row(
                        [
                            ft.Column(
                                [
                                    ft.Text(label, size=13, weight=ft.FontWeight.W_600, color="#ffffff"),
                                    ft.Text(identifier, size=10, color="#7c7c82")
                                ],
                                spacing=2,
                                expand=True
                            ),
                            ft.Switch(
                                value=identifier not in disabled_sources,
                                active_color="#00e676",
                                active_track_color="#1a3828",
                                on_change=lambda e, lid=identifier: self.on_toggle_channel(lid, e.control.value)
                            ),
                            ft.IconButton(
                                icon=ft.Icons.DELETE_OUTLINE,
                                icon_color="#ff1744",
                                icon_size=16,
                                on_click=lambda e, lid=identifier: self.on_delete_channel(lid)
                            )
                        ],
                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN
                    ),
                    bgcolor="#1e1e24",
                    padding=10,
                    border_radius=6,
                    border=ft.Border.all(1, "#26262b")
                )
            )
        self.page.update()

    def start_status_poller(self) -> None:
        """Start async thread to continuously refresh statuses and bridge data."""
        async def poll_state():
            while True:
                try:
                    self.poll_connection_status()
                    self.poll_bridge_trades()
                except Exception as exc:
                    logger.debug("GUI poller error: %s", exc)
                await asyncio.sleep(2.0)

        # Launch background poller tasks inside Flet loop
        self.page.run_task(poll_state)

    def poll_connection_status(self) -> None:
        """Check status of Telethon session and MT5 bridge folders."""
        # Check if listener process is active
        if self.listener_process is not None:
            ret = self.listener_process.poll()
            if ret is not None:
                # Process died
                self.listener_process = None
                self.is_listener_running = False
                self.start_stop_button.content = "START LISTENER"
                self.start_stop_button.style = ft.ButtonStyle(color="#00e676")
                self.page.update()

        # Read telegram_status.txt and ea_status.txt from bridge folder
        bridge_root = self.config.bridge_inbox_dir
        if bridge_root.name.lower() == "inbox":
            bridge_root = bridge_root.parent
            
        status_file = bridge_root / "telegram_status.txt"
        ea_status_file = bridge_root / "ea_status.txt"
        
        tg_connected = False
        mt5_connected = False
        
        if status_file.exists():
            try:
                status_text = status_file.read_text(encoding="utf-8")
                for line in status_text.splitlines():
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
                ea_text = ea_status_file.read_text(encoding="utf-8")
                ea_data = {}
                for line in ea_text.splitlines():
                    if "=" in line:
                        k, v = line.split("=", 1)
                        ea_data[k.strip()] = v.strip()
                
                hb_epoch = int(ea_data.get("heartbeat_epoch", "0"))
                if hb_epoch > 0:
                    current_epoch = int(time.time())
                    if abs(current_epoch - hb_epoch) < 20:
                        mt5_connected = True
            except Exception:
                pass

        # Update Indicators
        if tg_connected or self.is_listener_running:
            self.tg_status_icon.color = "#00e676"
            self.tg_status_text.value = "Connected (Running)"
        else:
            self.tg_status_icon.color = "#ff1744"
            self.tg_status_text.value = "Disconnected"
            
        if mt5_connected:
            self.mt5_status_icon.color = "#00e676"
            self.mt5_status_text.value = "Connected (EA Listening)"
        else:
            self.mt5_status_icon.color = "#ff1744"
            self.mt5_status_text.value = "Waiting (No Terminal)"

        self.page.update()

    def poll_bridge_trades(self) -> None:
        """Parse MT5 File Bridge directory for trade logs and outcome statuses."""
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
                    "symbol": cmd_data.get("symbol", ""),
                    "action": cmd_data.get("action", ""),
                    "volume": cmd_data.get("volume", ""),
                    "sl": cmd_data.get("stop_loss", ""),
                    "tp": cmd_data.get("take_profit", ""),
                    "status": res_data.get("status", "PENDING"),
                    "message": res_data.get("message", "")
                })
            except Exception:
                continue

        # Sort descending
        trades.sort(key=lambda x: x.get("time", "0"), reverse=True)
        self.active_trades = trades
        
        # Populate UI Table rows
        self.trades_table.rows.clear()
        
        total_trades = len(trades)
        successful = 0
        
        for t in trades[:15]:  # Show latest 15 trades
            time_val = t.get("time", "0")
            try:
                dt = datetime.datetime.fromtimestamp(float(time_val))
                time_str = dt.strftime("%H:%M:%S")
            except Exception:
                time_str = "unknown"
                
            status_val = t.get("status", "PENDING")
            status_color = "#00e676" if status_val == "FILLED" else ("#ff1744" if "FAIL" in status_val or "REJECT" in status_val else "#ffb300")
            
            if status_val == "FILLED":
                successful += 1
                
            self.trades_table.rows.append(
                ft.DataRow(
                    cells=[
                        ft.DataCell(ft.Text(time_str, size=12)),
                        ft.DataCell(ft.Text(t.get("symbol", ""), size=12, weight=ft.FontWeight.W_600)),
                        ft.DataCell(
                            ft.Text(
                                t.get("action", ""), 
                                size=11, 
                                color="#00e676" if t.get("action") == "BUY" else "#ff1744",
                                weight=ft.FontWeight.BOLD
                            )
                        ),
                        ft.DataCell(ft.Text(f"{t.get('volume', '')} lots", size=12)),
                        ft.DataCell(ft.Text(t.get("sl", ""), size=12, color="#ff1744")),
                        ft.DataCell(ft.Text(t.get("tp", ""), size=12, color="#00e676")),
                        ft.DataCell(
                            ft.Container(
                                content=ft.Text(status_val, size=10, weight=ft.FontWeight.BOLD, color="#ffffff"),
                                bgcolor=status_color,
                                padding=ft.Padding.symmetric(horizontal=8, vertical=2),
                                border_radius=4
                            )
                        ),
                    ]
                )
            )

        self.metric_total_trades.value = str(total_trades)
        self.metric_signals.value = str(total_trades)
        if total_trades > 0:
            rate = int((successful / total_trades) * 100)
            self.metric_success_rate.value = f"{rate}%"
        else:
            self.metric_success_rate.value = "0%"

        self.update_performance_chart()
        self.page.update()

    def update_performance_chart(self) -> None:
        """Draw a stylized trade outcomes histogram using containers."""
        if not self.active_trades:
            self.chart_container.content = ft.Text(
                "Waiting for trade signals to populate dashboard telemetry...", 
                size=12, 
                color="#7c7c82"
            )
            return

        # Show latest 15 trades (earliest first for left-to-right timeline)
        recent_trades = list(reversed(self.active_trades[:15]))
        
        bars = []
        for t in recent_trades:
            status = t.get("status", "PENDING")
            action = t.get("action", "BUY")
            symbol = t.get("symbol", "")
            vol = t.get("volume", "0.01")
            
            # Determine color and height based on trade status/action
            if status == "FILLED":
                color = "#00e5ff" if action == "BUY" else "#00e676"  # Cyan/Green for filled
                height = 80
            elif "FAIL" in status or "REJECT" in status:
                color = "#ff1744"  # Red for failed
                height = 30
            else:
                color = "#ffb300"  # Amber for pending
                height = 50
                
            bars.append(
                ft.Container(
                    width=24,
                    height=height,
                    bgcolor=color,
                    border_radius=4,
                    tooltip=f"{symbol} {action} {vol}\nStatus: {status}",
                    animate_size=300
                )
            )
            
        self.chart_container.content = ft.Row(
            controls=bars,
            alignment=ft.MainAxisAlignment.CENTER,
            vertical_alignment=ft.CrossAxisAlignment.END,
            spacing=8
        )

    # --- Action event handlers ---

    def on_toggle_channel(self, identifier: str, is_enabled: bool) -> None:
        """Called when a channel's enable switch is toggled."""
        disabled_sources = self.settings_manager.get("disabled_sources", [])
        if is_enabled:
            if identifier in disabled_sources:
                disabled_sources.remove(identifier)
        else:
            if identifier not in disabled_sources:
                disabled_sources.append(identifier)
        self.settings_manager.set("disabled_sources", disabled_sources)
        self.page.show_dialog(ft.SnackBar(content=ft.Text(f"Channel {'enabled' if is_enabled else 'disabled'} successfully")))
        self.refresh_channels_list()

    def on_delete_channel(self, identifier: str) -> None:
        """Remove a channel from settings.json and update UI."""
        sources: list[str] = self.settings_manager.get("telegram_sources", [])
        updated = []
        for src in sources:
            label, ident = _parse_source_spec(src)
            if ident != identifier:
                updated.append(src)
        
        self.settings_manager.set("telegram_sources", updated)
        self.refresh_channels_list()

    def on_search_channels(self, e: ft.ControlEvent) -> None:
        self.refresh_channels_list()

    def on_add_channel_dialog(self, e: ft.ControlEvent) -> None:
        # Show input popup dialog with searching capability
        search_field = ft.TextField(
            label="Search joined Telegram groups/channels...",
            autofocus=True,
            on_change=lambda ev: self.populate_dialogs_list(results_list, ev.control.value)
        )
        results_list = ft.ListView(expand=True, spacing=5, height=220)
        progress_indicator = ft.ProgressRing(visible=True, width=20, height=20)
        status_text = ft.Text("Loading groups...", size=11, color="#7c7c82")
        
        manual_name = ft.TextField(label="Custom Label / Name")
        manual_ident = ft.TextField(label="Username (e.g. @channel) or Chat ID")
        
        def on_manual_add(ev):
            name = manual_name.value.strip()
            ident = manual_ident.value.strip()
            if not name or not ident:
                return
            sources = self.settings_manager.get("telegram_sources", [])
            sources.append(f"{name}::{ident}")
            self.settings_manager.set("telegram_sources", sources)
            self.refresh_channels_list()
            self.page.show_dialog(ft.SnackBar(content=ft.Text(f"Added custom source: {name}")))
            self.page.pop_dialog()

        dlg = ft.AlertDialog(
            title=ft.Text("Add Telegram Channel/Group"),
            content=ft.Container(
                content=ft.Column(
                    [
                        search_field,
                        ft.Row([progress_indicator, status_text], spacing=8),
                        results_list,
                        ft.Divider(color="#26262b"),
                        ft.ExpansionTile(
                            title=ft.Text("Manually Add Custom Channel", size=12, weight=ft.FontWeight.W_600),
                            controls=[
                                ft.Column(
                                    [
                                        manual_name,
                                        manual_ident,
                                        ft.ElevatedButton(
                                            "Add Custom Channel", 
                                            bgcolor="#00e5ff", 
                                            color="#121214", 
                                            on_click=on_manual_add
                                        )
                                    ],
                                    spacing=10
                                )
                            ]
                        )
                    ],
                    tight=True,
                    spacing=10
                ),
                width=500
            ),
            actions=[
                ft.TextButton("Cancel", on_click=lambda ev: self.page.pop_dialog())
            ],
            actions_alignment=ft.MainAxisAlignment.END
        )
        self.page.show_dialog(dlg)
        # Load dialogs asynchronously in Flet background task
        self.page.run_task(self.load_dialogs_async, results_list, progress_indicator, status_text)

    async def load_dialogs_async(self, results_list: ft.ListView, progress_indicator: ft.ProgressRing, status_text: ft.Text) -> None:
        import json
        bridge_root = self.config.bridge_inbox_dir
        if bridge_root.name.lower() == "inbox":
            bridge_root = bridge_root.parent
        dialogs_file = bridge_root / "telegram_dialogs.json"
        
        cached_dialogs = []
        if dialogs_file.exists():
            try:
                cached_dialogs = json.loads(dialogs_file.read_text(encoding="utf-8"))
            except Exception:
                pass
                
        self._all_telegram_dialogs = cached_dialogs
        self.populate_dialogs_list(results_list)
        
        if not self.is_listener_running:
            try:
                status_text.value = "Refreshing groups list from Telegram..."
                status_text.update()
            except Exception:
                pass
            try:
                from telegram_signal_copier.services.telegram_session import TelegramSessionService
                srv = TelegramSessionService(self.config)
                fresh_dialogs = await srv.list_dialogs(limit=250)
                dialogs_file.write_text(json.dumps(fresh_dialogs, indent=2, ensure_ascii=False), encoding="utf-8")
                self._all_telegram_dialogs = fresh_dialogs
                self.populate_dialogs_list(results_list)
                status_text.value = f"Loaded {len(fresh_dialogs)} groups from Telegram."
            except Exception as exc:
                logger.debug("Failed dynamic dialog fetch: %s", exc)
                status_text.value = f"Loaded {len(cached_dialogs)} groups from cache (offline)."
        else:
            status_text.value = f"Loaded {len(cached_dialogs)} groups from cache (active listener)."
            
        progress_indicator.visible = False
        try:
            progress_indicator.update()
        except Exception:
            pass
        try:
            status_text.update()
        except Exception:
            pass

    def populate_dialogs_list(self, results_list: ft.ListView, query: str = "") -> None:
        results_list.controls.clear()
        query = query.lower().strip()
        
        configured_ids = {str(ident) for _, ident in self.config.telegram_source_mappings}
        
        count = 0
        for dlg in self._all_telegram_dialogs:
            title = dlg.get("title", "")
            username = dlg.get("username", "") or ""
            ident = str(dlg.get("id", ""))
            
            if query and (query not in title.lower() and query not in username.lower() and query not in ident):
                continue
                
            is_added = ident in configured_ids or (username and f"@{username}" in configured_ids)
            
            results_list.controls.append(
                ft.Container(
                    content=ft.Row(
                        [
                            ft.Icon(
                                ft.Icons.SETTINGS_INPUT_ANTENNA if dlg.get("is_channel") else ft.Icons.PEOPLE_ALT,
                                color="#00e5ff" if dlg.get("is_channel") else "#00e676",
                                size=20
                            ),
                            ft.Column(
                                [
                                    ft.Text(title, size=12, weight=ft.FontWeight.BOLD, color="#ffffff"),
                                    ft.Text(f"@{username}" if username else f"ID: {ident}", size=10, color="#7c7c82")
                                ],
                                spacing=2,
                                expand=True
                            ),
                            ft.IconButton(
                                icon=ft.Icons.CHECK if is_added else ft.Icons.ADD,
                                icon_color="#7c7c82" if is_added else "#00e676",
                                tooltip="Already Added" if is_added else "Add Channel",
                                disabled=is_added,
                                on_click=lambda e, t=title, i=ident, u=username: self.add_dialog_to_sources(t, i, u)
                            )
                        ],
                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN
                    ),
                    padding=8,
                    bgcolor="#26262b" if is_added else "#1e1e24",
                    border_radius=5,
                    border=ft.Border.all(1, "#36363b")
                )
            )
            count += 1
            if count >= 50:
                break
                
        if not results_list.controls:
            results_list.controls.append(ft.Text("No matching groups found.", size=12, color="#7c7c82"))
            
        try:
            results_list.update()
        except Exception:
            pass

    def add_dialog_to_sources(self, title: str, ident: str, username: str) -> None:
        target_id = f"@{username}" if username else ident
        sources = self.settings_manager.get("telegram_sources", [])
        sources.append(f"{title}::{target_id}")
        self.settings_manager.set("telegram_sources", sources)
        
        self.refresh_channels_list()
        self.page.show_dialog(ft.SnackBar(content=ft.Text(f"Added source: {title}")))
        self.page.pop_dialog()

    def on_clear_trades(self, e: ft.ControlEvent) -> None:
        """Clear the visual active trades list (deletes files from bridge folder)."""
        bridge_dir = self.config.bridge_inbox_dir
        if not bridge_dir.exists():
            return
        
        for item in bridge_dir.glob("*.txt"):
            if item.name in {"command_queue.txt", "telegram_sources.txt", "telegram_status.txt"}:
                continue
            try:
                item.unlink()
            except Exception:
                pass
        
        outbox_dir = bridge_dir / "outbox"
        if outbox_dir.exists():
            for item in outbox_dir.glob("*.result"):
                try:
                    item.unlink()
                except Exception:
                    pass
        
        self.poll_bridge_trades()

    def on_start_listener(self, e: ft.ControlEvent) -> None:
        """Start or Stop the copier background listener daemon process."""
        if self.is_listener_running:
            # Stop the process
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
            
            self.is_listener_running = False
            self.start_stop_button.content = "START LISTENER"
            self.start_stop_button.style = ft.ButtonStyle(color="#00e676")
        else:
            # Start process
            py_exe = sys.executable
            if getattr(sys, "frozen", False):
                args = [py_exe, "listen"]
            else:
                args = [py_exe, "-m", "telegram_signal_copier.main", "listen"]
            
            # Start listener background process
            try:
                self.listener_process = subprocess.Popen(
                    args,
                    cwd=str(self.project_root),
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL
                )
                self.is_listener_running = True
                self.start_stop_button.content = "STOP LISTENER"
                self.start_stop_button.style = ft.ButtonStyle(color="#ff1744")
            except Exception as exc:
                self.page.show_dialog(ft.SnackBar(content=ft.Text(f"Failed to start listener: {exc}")))
        
        self.page.update()

    def on_save_quick_lot(self, e: ft.ControlEvent) -> None:
        try:
            val = float(self.quick_lot_input.value)
            self.settings_manager.set("default_volume", val)
            self.page.show_dialog(ft.SnackBar(content=ft.Text(f"Quick lot size set to {val}!")))
        except ValueError:
            self.page.show_dialog(ft.SnackBar(content=ft.Text("Invalid lot size! must be a float number.")))

    def on_quick_lot_mode_change(self, e: ft.ControlEvent) -> None:
        pass

    # --- Settings Dialog ---

    def on_open_settings(self, e: Any = None) -> None:
        # Create fields loaded with current settings.json state
        api_id_field = ft.TextField(label="Telegram API ID", value=str(self.settings_manager.get("telegram_api_id", "")))
        api_hash_field = ft.TextField(label="Telegram API Hash", value=self.settings_manager.get("telegram_api_hash", ""))
        phone_field = ft.TextField(label="Phone Number (e.g. +1...)", value=self.settings_manager.get("telegram_phone_number", ""))
        openai_key_field = ft.TextField(label="OpenAI API Key", password=True, can_reveal_password=True, value=self.settings_manager.get("openai_api_key", ""))
        openai_model_field = ft.TextField(label="OpenAI Model", value=self.settings_manager.get("openai_model", "gpt-4o-mini"))
        
        max_lot_field = ft.TextField(label="Maximum Lot Size", value=str(self.settings_manager.get("maximum_lot_size", "10.0")))
        symbol_suffix_field = ft.TextField(label="Broker Symbol Suffix (e.g. 'm')", value=self.settings_manager.get("mt5_symbol_suffix", ""))
        min_confidence_field = ft.TextField(label="Minimum AI Confidence (0.0-1.0)", value=str(self.settings_manager.get("minimum_confidence", "0.45")))
        
        # Filtering fields
        time_filter_switch = ft.Switch(label="Enable Time Range Filter", value=self.settings_manager.get("enable_time_filter", False))
        time_from_field = ft.TextField(label="From Time (HH:MM)", value=self.settings_manager.get("time_from", "00:00"), width=120)
        time_to_field = ft.TextField(label="To Time (HH:MM)", value=self.settings_manager.get("time_to", "23:59"), width=120)
        
        # Custom Keywords
        buy_keywords_field = ft.TextField(
            label="BUY keywords (comma-separated)",
            value=",".join(self.settings_manager.get("custom_buy_keywords", ["LONG", "CALL", "BULLISH", "BUY"]))
        )
        sell_keywords_field = ft.TextField(
            label="SELL keywords (comma-separated)",
            value=",".join(self.settings_manager.get("custom_sell_keywords", ["SHORT", "PUT", "BEARISH", "SELL"]))
        )

        def close_settings(ev):
            self.page.pop_dialog()

        def save_settings(ev):
            # Save settings fields to settings_manager cache
            self.settings_manager.set("telegram_api_id", api_id_field.value.strip())
            self.settings_manager.set("telegram_api_hash", api_hash_field.value.strip())
            self.settings_manager.set("telegram_phone_number", phone_field.value.strip())
            self.settings_manager.set("openai_api_key", openai_key_field.value.strip())
            self.settings_manager.set("openai_model", openai_model_field.value.strip())
            self.settings_manager.set("mt5_symbol_suffix", symbol_suffix_field.value.strip())
            
            try:
                self.settings_manager.set("maximum_lot_size", float(max_lot_field.value.strip()))
                self.settings_manager.set("minimum_confidence", float(min_confidence_field.value.strip()))
            except ValueError:
                pass
                
            self.settings_manager.set("enable_time_filter", time_filter_switch.value)
            self.settings_manager.set("time_from", time_from_field.value.strip())
            self.settings_manager.set("time_to", time_to_field.value.strip())
            
            # Keywords
            buy_list = [k.strip() for k in buy_keywords_field.value.split(",") if k.strip()]
            sell_list = [k.strip() for k in sell_keywords_field.value.split(",") if k.strip()]
            self.settings_manager.set("custom_buy_keywords", buy_list)
            self.settings_manager.set("custom_sell_keywords", sell_list)
            
            self.page.show_dialog(ft.SnackBar(content=ft.Text("Settings saved successfully! (Config is updated)")))
            close_settings(ev)
            self.refresh_channels_list()

        tabs = ft.Tabs(
            length=4,
            selected_index=0,
            expand=True,
            content=ft.Column(
                expand=True,
                controls=[
                    ft.TabBar(
                        tabs=[
                            ft.Tab(label="Trading Credentials"),
                            ft.Tab(label="AI Provider Options"),
                            ft.Tab(label="Time Range Filters"),
                            ft.Tab(label="Keywords Parsing"),
                        ]
                    ),
                    ft.TabBarView(
                        expand=True,
                        controls=[
                            ft.Container(
                                content=ft.Column(
                                    [
                                        api_id_field,
                                        api_hash_field,
                                        phone_field,
                                        symbol_suffix_field,
                                    ],
                                    spacing=10,
                                    scroll=ft.ScrollMode.ALWAYS,
                                ),
                                padding=15
                            ),
                            ft.Container(
                                content=ft.Column(
                                    [
                                        openai_key_field,
                                        openai_model_field,
                                        min_confidence_field,
                                    ],
                                    spacing=10,
                                    scroll=ft.ScrollMode.ALWAYS,
                                ),
                                padding=15
                            ),
                            ft.Container(
                                content=ft.Column(
                                    [
                                        time_filter_switch,
                                        ft.Row([time_from_field, time_to_field], spacing=10),
                                        ft.Text("Define hours during which trades are permitted to copy.", size=11, color="#7c7c82")
                                    ],
                                    spacing=10,
                                    scroll=ft.ScrollMode.ALWAYS,
                                ),
                                padding=15
                            ),
                            ft.Container(
                                content=ft.Column(
                                    [
                                        buy_keywords_field,
                                        sell_keywords_field,
                                        ft.Text("Define custom words to classify signals into BUY/SELL orders.", size=11, color="#7c7c82")
                                    ],
                                    spacing=10,
                                    scroll=ft.ScrollMode.ALWAYS,
                                ),
                                padding=15
                            ),
                        ]
                    )
                ]
            )
        )

        dlg = ft.AlertDialog(
            title=ft.Row(
                [
                    ft.Icon(ft.Icons.SETTINGS, color="#00e5ff"),
                    ft.Text("TradeSync Parameters Configuration")
                ],
                spacing=8
            ),
            content=ft.Container(
                content=tabs,
                width=550,
                height=350
            ),
            actions=[
                ft.TextButton("Cancel", on_click=close_settings),
                ft.ElevatedButton("Save Settings", bgcolor="#00e5ff", color="#121214", on_click=save_settings)
            ],
            actions_alignment=ft.MainAxisAlignment.END
        )
        self.page.show_dialog(dlg)


def main(page: ft.Page) -> None:
    SignalCopierDashboard(page)


if __name__ == "__main__":
    ft.app(target=main)
