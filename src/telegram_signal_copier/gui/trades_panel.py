"""Trades panel — active trades table, P&L chart, and demo data seeding."""
from __future__ import annotations

import datetime
import logging
import random
import time
from typing import Any

import flet as ft

from telegram_signal_copier.config import AppConfig
from telegram_signal_copier.gui.theme import (
    BG_DARK,
    BG_PANEL,
    BORDER,
    ERROR,
    PRIMARY,
    SECONDARY,
    TEXT_PRIMARY,
    TEXT_SECONDARY,
    WARNING,
)

logger = logging.getLogger(__name__)


class TradesPanel:
    """Central dashboard area: trades list and performance chart."""

    def __init__(self, page: ft.Page, config: AppConfig) -> None:
        self.page = page
        self.config = config
        self.active_trades: list[dict[str, Any]] = []

        self.trades_table = self._build_trades_table()
        self.chart_container = self._build_chart_container()
        self.center_area = self._build_center_area()

    # ── UI builders ────────────────────────────────────────────────────────

    def _build_trades_table(self) -> ft.DataTable:
        return ft.DataTable(
            columns=[
                ft.DataColumn(ft.Text("Time", size=11, color=TEXT_SECONDARY)),
                ft.DataColumn(ft.Text("Source", size=11, color=TEXT_SECONDARY)),
                ft.DataColumn(ft.Text("Symbol", size=11, color=TEXT_SECONDARY)),
                ft.DataColumn(ft.Text("Type", size=11, color=TEXT_SECONDARY)),
                ft.DataColumn(ft.Text("Entry", size=11, color=TEXT_SECONDARY)),
                ft.DataColumn(ft.Text("SL", size=11, color=TEXT_SECONDARY)),
                ft.DataColumn(ft.Text("TP", size=11, color=TEXT_SECONDARY)),
                ft.DataColumn(ft.Text("Status", size=11, color=TEXT_SECONDARY)),
            ],
            rows=[],
            heading_row_height=30,
            data_row_min_height=32,
            data_row_max_height=36,
            horizontal_margin=10,
            column_spacing=12,
        )

    def _build_chart_container(self) -> ft.Container:
        return ft.Container(
            content=ft.Column(
                [ft.Text("Waiting for trade signals...", size=12, color=TEXT_SECONDARY)],
                alignment=ft.MainAxisAlignment.CENTER,
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            alignment=ft.Alignment.CENTER,
            bgcolor=BG_PANEL,
            height=240,
            border_radius=6,
            border=ft.Border.all(1, BORDER),
        )

    def _build_center_area(self) -> ft.Container:
        return ft.Container(
            content=ft.Column(
                [
                    ft.Row(
                        [
                            ft.Text("ACTIVE TRADES", size=13, weight=ft.FontWeight.BOLD, color=TEXT_PRIMARY),
                            ft.TextButton(
                                "Clear",
                                icon=ft.Icons.DELETE_SWEEP,
                                style=ft.ButtonStyle(color=ERROR, text_style=ft.TextStyle(size=12)),
                                on_click=self.on_clear_trades,
                            ),
                        ],
                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                    ),
                    ft.Container(
                        content=ft.Column([self.trades_table], scroll=ft.ScrollMode.ALWAYS),
                        expand=True,
                        bgcolor=BG_PANEL,
                        border_radius=6,
                        border=ft.Border.all(1, BORDER),
                        padding=ft.Padding.symmetric(horizontal=8, vertical=6),
                    ),
                    ft.Text("P&L PERFORMANCE", size=12, weight=ft.FontWeight.W_600, color=TEXT_PRIMARY),
                    self.chart_container,
                ],
                spacing=8,
                expand=True,
            ),
            expand=True,
            padding=ft.Padding.only(left=15, right=15, top=15, bottom=15),
        )

    # ── Data population ────────────────────────────────────────────────────

    def populate_trades(self, trades: list[dict[str, Any]]) -> None:
        """Fill the trades table from a list of trade dicts."""
        self.trades_table.rows.clear()
        for t in trades[:15]:
            time_str = self._format_time(t.get("time", "0"))
            status_val = t.get("status", "PENDING")
            profit_val = self._safe_float(t.get("profit", ""))
            status_color = self._status_color(status_val, profit_val)
            source = t.get("source_group", "")
            if len(source) > 14:
                source = source[:12] + ".."

            self.trades_table.rows.append(
                ft.DataRow(
                    cells=[
                        ft.DataCell(ft.Text(time_str, size=12)),
                        ft.DataCell(ft.Text(source, size=10, color=TEXT_SECONDARY)),
                        ft.DataCell(ft.Text(t.get("symbol", ""), size=12, weight=ft.FontWeight.W_600)),
                        ft.DataCell(
                            ft.Text(
                                t.get("action", ""),
                                size=11,
                                color=SECONDARY if t.get("action") == "BUY" else ERROR,
                                weight=ft.FontWeight.BOLD,
                            )
                        ),
                        ft.DataCell(ft.Text(f"{t.get('volume', '')} lots", size=12)),
                        ft.DataCell(ft.Text(t.get("sl", ""), size=12, color=ERROR)),
                        ft.DataCell(ft.Text(t.get("tp", ""), size=12, color=SECONDARY)),
                        ft.DataCell(
                            ft.Container(
                                content=ft.Text(status_val, size=10, weight=ft.FontWeight.BOLD, color=TEXT_PRIMARY),
                                bgcolor=status_color,
                                padding=ft.Padding.symmetric(horizontal=8, vertical=2),
                                border_radius=4,
                            )
                        ),
                    ]
                )
            )

    def update_performance_chart(self, trades: list[dict[str, Any]]) -> None:
        """Draw P&L performance bars from trade outcomes."""
        if not trades:
            self.chart_container.content = ft.Column(
                [
                    ft.Text("No trade data available.", size=12, color=TEXT_SECONDARY),
                    ft.Text("Start listener or ensure MT5 EA writes outbox results.", size=11, color=TEXT_SECONDARY, italic=True),
                ],
                alignment=ft.MainAxisAlignment.CENTER,
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            )
            return

        recent = list(reversed(trades[:20]))
        cumulative_pnl = 0.0
        bars: list[ft.Control] = []
        pnl_labels: list[ft.Control] = []

        for t in recent:
            status = t.get("status", "PENDING")
            trade_pnl = self._safe_float(t.get("profit", ""))
            color = self._bar_color(status, trade_pnl)
            cumulative_pnl += trade_pnl

            bar_height = max(10, min(120, int(abs(trade_pnl) * 2.5))) if trade_pnl != 0 else 10
            is_profit = trade_pnl >= 0

            bars.append(
                ft.Container(
                    width=22,
                    height=bar_height,
                    bgcolor=color,
                    border_radius=ft.border_radius.only(
                        top_left=4, top_right=4,
                        bottom_left=0 if is_profit else 4,
                        bottom_right=0 if is_profit else 4,
                    ),
                    tooltip=f"{t.get('source_group', '')} | {t.get('symbol', '')} {t.get('action', '')}\nP&L: ${trade_pnl:+.2f}",
                    animate_size=300,
                )
            )
            pnl_labels.append(
                ft.Container(
                    content=ft.Text(
                        f"${trade_pnl:+.0f}",
                        size=7,
                        color=TEXT_PRIMARY if abs(trade_pnl) > 5 else TEXT_SECONDARY,
                        weight=ft.FontWeight.W_600,
                    ),
                    alignment=ft.alignment.center,
                )
            )

        won = len([t for t in recent if t.get("status") == "FILLED"])
        lost = len([t for t in recent if "FAIL" in t.get("status", "") or "REJECT" in t.get("status", "")])

        self.chart_container.content = ft.Column(
            [
                ft.Row(
                    [
                        ft.Text(f"Cumulative P&L: ${cumulative_pnl:+.2f}", size=13, weight=ft.FontWeight.BOLD, color=TEXT_PRIMARY),
                        ft.Text(f"({won} won / {lost} lost)", size=10, color=TEXT_SECONDARY),
                    ],
                    alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                ),
                ft.Container(
                    content=ft.Row(controls=bars, alignment=ft.MainAxisAlignment.CENTER, vertical_alignment=ft.CrossAxisAlignment.END, spacing=5),
                    bgcolor=BG_DARK,
                    border_radius=4,
                    padding=ft.Padding.only(top=10, bottom=5, left=5, right=5),
                    expand=True,
                ),
                ft.Container(content=ft.Row(controls=pnl_labels, alignment=ft.MainAxisAlignment.CENTER, spacing=5), height=20),
            ],
            spacing=4,
        )

    def seed_demo_trades(self) -> None:
        """Generate sample trade data for dashboard display."""
        now = time.time()
        symbols = ["XAUUSD", "EURUSD", "GBPUSD", "BTCUSD", "ETHUSD", "USDJPY"]
        sources = ["Gold Signals", "FX Masters", "Crypto Alpha", "Forex Premium"]
        statuses = ["FILLED"] * 6 + ["FAIL", "PENDING", "TIMEOUT"]

        demo: list[dict[str, Any]] = []
        for i in range(30):
            ts = now - (30 - i) * 180
            price = round(random.uniform(1800, 2100), 2) if random.random() > 0.5 else round(random.uniform(1.05, 1.15), 5)
            sl = round(price - (price * 0.005), 5)
            tp = round(price + (price * 0.01), 5)
            demo.append({
                "time": str(int(ts)),
                "source_group": random.choice(sources),
                "symbol": random.choice(symbols),
                "action": random.choice(["BUY", "SELL"]),
                "volume": str(round(random.uniform(0.1, 2.0), 2)),
                "sl": str(sl),
                "tp": str(tp),
                "status": random.choice(statuses),
                "message": "",
            })

        demo.sort(key=lambda x: x.get("time", "0"), reverse=True)
        self.active_trades = demo
        logger.info("Seeded %d demo trades for dashboard display", len(demo))

    # ── Event handlers ─────────────────────────────────────────────────────

    def on_clear_trades(self, e: Any = None) -> None:
        """Clear bridge trade files and refresh."""
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
        outbox = bridge_dir / "outbox"
        if outbox.exists():
            for item in outbox.glob("*.result"):
                try:
                    item.unlink()
                except Exception:
                    pass

    # ── Helpers ────────────────────────────────────────────────────────────

    @staticmethod
    def _format_time(epoch_str: str) -> str:
        try:
            return datetime.datetime.fromtimestamp(float(epoch_str)).strftime("%H:%M:%S")
        except Exception:
            return "unknown"

    @staticmethod
    def _safe_float(val: str) -> float:
        try:
            return float(val) if val else 0.0
        except (ValueError, TypeError):
            return 0.0

    @staticmethod
    def _status_color(status: str, profit: float) -> str:
        if profit > 0 or status in {"TP_HIT"}:
            return SECONDARY
        if profit < 0 or "FAIL" in status or "REJECT" in status or status == "SL_HIT":
            return ERROR
        return WARNING

    @staticmethod
    def _bar_color(status: str, profit: float) -> str:
        if status == "FILLED" and profit != 0.0:
            return SECONDARY if profit > 0 else ERROR
        if "FAIL" in status or "REJECT" in status:
            return ERROR
        if "TIMEOUT" in status or "NOT_CONSUMED" in status:
            return WARNING
        return WARNING
