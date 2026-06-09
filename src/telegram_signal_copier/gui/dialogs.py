"""GUI dialogs — add channel, settings, and Telegram group loader."""
from __future__ import annotations

import json
import logging
from typing import Any

import flet as ft

from telegram_signal_copier.config import AppConfig
from telegram_signal_copier.config_helpers import _parse_source_spec
from telegram_signal_copier.gui.theme import (
    BADGE_BG,
    BORDER,
    INPUT_BORDER,
    PRIMARY,
    SECONDARY,
    TEXT_PRIMARY,
    TEXT_SECONDARY,
)
from telegram_signal_copier.services.settings_manager import SettingsManager

logger = logging.getLogger(__name__)


def show_add_channel_dialog(
    page: ft.Page,
    config: AppConfig,
    settings_manager: SettingsManager,
    refresh_callback: Any,
) -> None:
    """Show dialog to search/add Telegram channels."""
    search_field = ft.TextField(
        label="Search joined Telegram groups/channels...",
        autofocus=True,
    )
    results_list = ft.ListView(expand=True, spacing=5, height=220)
    progress_indicator = ft.ProgressRing(visible=True, width=20, height=20)
    status_text = ft.Text("Loading groups...", size=11, color=TEXT_SECONDARY)

    manual_name = ft.TextField(label="Custom Label / Name")
    manual_ident = ft.TextField(label="Username (e.g. @channel) or Chat ID")

    # Store all dialogs for filtering
    all_dialogs: list[dict[str, Any]] = []

    def populate_results(query: str = "") -> None:
        results_list.controls.clear()
        query = query.lower().strip()
        configured_ids = {str(ident) for _, ident in config.telegram_source_mappings}
        count = 0

        for dlg in all_dialogs:
            title = dlg.get("title", "")
            username = dlg.get("username", "") or ""
            ident = str(dlg.get("id", ""))

            if query and query not in title.lower() and query not in username.lower() and query not in ident:
                continue

            is_added = ident in configured_ids or (username and f"@{username}" in configured_ids)

            results_list.controls.append(
                ft.Container(
                    content=ft.Row(
                        [
                            ft.Icon(
                                ft.Icons.SETTINGS_INPUT_ANTENNA if dlg.get("is_channel") else ft.Icons.PEOPLE_ALT,
                                color=PRIMARY if dlg.get("is_channel") else SECONDARY,
                                size=20,
                            ),
                            ft.Column(
                                [
                                    ft.Text(title, size=12, weight=ft.FontWeight.BOLD, color=TEXT_PRIMARY),
                                    ft.Text(f"@{username}" if username else f"ID: {ident}", size=10, color=TEXT_SECONDARY),
                                ],
                                spacing=2,
                                expand=True,
                            ),
                            ft.IconButton(
                                icon=ft.Icons.CHECK if is_added else ft.Icons.ADD,
                                icon_color=TEXT_SECONDARY if is_added else SECONDARY,
                                tooltip="Already Added" if is_added else "Add Channel",
                                disabled=is_added,
                                on_click=lambda e, t=title, i=ident, u=username: _add_source(t, i, u),
                            ),
                        ],
                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                    ),
                    padding=8,
                    bgcolor="#26262b" if is_added else "#1e1e24",
                    border_radius=5,
                    border=ft.Border.all(1, "#36363b"),
                )
            )
            count += 1
            if count >= 50:
                break

        if not results_list.controls:
            results_list.controls.append(ft.Text("No matching groups found.", size=12, color=TEXT_SECONDARY))
        try:
            results_list.update()
        except Exception:
            pass

    def _add_source(title: str, ident: str, username: str) -> None:
        target_id = f"@{username}" if username else ident
        sources = settings_manager.get("telegram_sources", [])
        sources.append(f"{title}::{target_id}")
        settings_manager.set("telegram_sources", sources)
        refresh_callback()
        page.show_dialog(ft.SnackBar(content=ft.Text(f"Added source: {title}")))
        page.pop_dialog()

    def on_manual_add(ev: Any) -> None:
        name = manual_name.value.strip()
        ident = manual_ident.value.strip()
        if not name or not ident:
            return
        sources = settings_manager.get("telegram_sources", [])
        sources.append(f"{name}::{ident}")
        settings_manager.set("telegram_sources", sources)
        refresh_callback()
        page.show_dialog(ft.SnackBar(content=ft.Text(f"Added custom source: {name}")))
        page.pop_dialog()

    search_field.on_change = lambda ev: populate_results(ev.control.value)

    dlg = ft.AlertDialog(
        title=ft.Text("Add Telegram Channel/Group"),
        content=ft.Container(
            content=ft.Column(
                [
                    search_field,
                    ft.Row([progress_indicator, status_text], spacing=8),
                    results_list,
                    ft.Divider(color=BORDER),
                    ft.ExpansionTile(
                        title=ft.Text("Manually Add Custom Channel", size=12, weight=ft.FontWeight.W_600),
                        controls=[
                            ft.Column(
                                [
                                    manual_name,
                                    manual_ident,
                                    ft.ElevatedButton(
                                        "Add Custom Channel",
                                        bgcolor=PRIMARY,
                                        color="#121214",
                                        on_click=on_manual_add,
                                    ),
                                ],
                                spacing=10,
                            )
                        ],
                    ),
                ],
                tight=True,
                spacing=10,
            ),
            width=500,
        ),
        actions=[ft.TextButton("Cancel", on_click=lambda ev: page.pop_dialog())],
        actions_alignment=ft.MainAxisAlignment.END,
    )
    page.show_dialog(dlg)

    # Load dialogs async
    page.run_task(_load_dialogs_async, config, all_dialogs, populate_results, progress_indicator, status_text)


async def _load_dialogs_async(
    config: AppConfig,
    all_dialogs: list[dict[str, Any]],
    populate_results: Any,
    progress_indicator: ft.ProgressRing,
    status_text: ft.Text,
) -> None:
    """Load Telegram dialogs from cache or live fetch."""
    bridge_root = config.bridge_inbox_dir
    if bridge_root.name.lower() == "inbox":
        bridge_root = bridge_root.parent
    dialogs_file = bridge_root / "telegram_dialogs.json"

    cached: list[dict[str, Any]] = []
    if dialogs_file.exists():
        try:
            cached = json.loads(dialogs_file.read_text(encoding="utf-8"))
        except Exception:
            pass

    all_dialogs.clear()
    all_dialogs.extend(cached)
    populate_results()

    try:
        status_text.value = f"Loaded {len(cached)} groups from cache."
        status_text.update()
    except Exception:
        pass

    progress_indicator.visible = False
    try:
        progress_indicator.update()
    except Exception:
        pass


def show_settings_dialog(
    page: ft.Page,
    settings_manager: SettingsManager,
    refresh_callback: Any,
) -> None:
    """Show settings dialog with tabs for credentials, AI, filters, keywords."""
    api_id_field = ft.TextField(label="Telegram API ID", value=str(settings_manager.get("telegram_api_id", "")))
    api_hash_field = ft.TextField(label="Telegram API Hash", value=settings_manager.get("telegram_api_hash", ""))
    phone_field = ft.TextField(label="Phone Number (e.g. +1...)", value=settings_manager.get("telegram_phone_number", ""))
    openai_key_field = ft.TextField(label="OpenAI API Key", password=True, can_reveal_password=True, value=settings_manager.get("openai_api_key", ""))
    openai_model_field = ft.TextField(label="OpenAI Model", value=settings_manager.get("openai_model", "gpt-4o-mini"))
    max_lot_field = ft.TextField(label="Maximum Lot Size", value=str(settings_manager.get("maximum_lot_size", "10.0")))
    symbol_suffix_field = ft.TextField(label="Broker Symbol Suffix (e.g. 'm')", value=settings_manager.get("mt5_symbol_suffix", ""))
    min_confidence_field = ft.TextField(label="Minimum AI Confidence (0.0-1.0)", value=str(settings_manager.get("minimum_confidence", "0.45")))
    time_filter_switch = ft.Switch(label="Enable Time Range Filter", value=settings_manager.get("enable_time_filter", False))
    time_from_field = ft.TextField(label="From Time (HH:MM)", value=settings_manager.get("time_from", "00:00"), width=120)
    time_to_field = ft.TextField(label="To Time (HH:MM)", value=settings_manager.get("time_to", "23:59"), width=120)
    buy_keywords_field = ft.TextField(
        label="BUY keywords (comma-separated)",
        value=",".join(settings_manager.get("custom_buy_keywords", ["LONG", "CALL", "BULLISH", "BUY"])),
    )
    sell_keywords_field = ft.TextField(
        label="SELL keywords (comma-separated)",
        value=",".join(settings_manager.get("custom_sell_keywords", ["SHORT", "PUT", "BEARISH", "SELL"])),
    )

    def close_settings(ev: Any) -> None:
        page.pop_dialog()

    def save_settings(ev: Any) -> None:
        settings_manager.set("telegram_api_id", api_id_field.value.strip())
        settings_manager.set("telegram_api_hash", api_hash_field.value.strip())
        settings_manager.set("telegram_phone_number", phone_field.value.strip())
        settings_manager.set("openai_api_key", openai_key_field.value.strip())
        settings_manager.set("openai_model", openai_model_field.value.strip())
        settings_manager.set("mt5_symbol_suffix", symbol_suffix_field.value.strip())
        try:
            settings_manager.set("maximum_lot_size", float(max_lot_field.value.strip()))
            settings_manager.set("minimum_confidence", float(min_confidence_field.value.strip()))
        except ValueError:
            pass
        settings_manager.set("enable_time_filter", time_filter_switch.value)
        settings_manager.set("time_from", time_from_field.value.strip())
        settings_manager.set("time_to", time_to_field.value.strip())
        buy_list = [k.strip() for k in buy_keywords_field.value.split(",") if k.strip()]
        sell_list = [k.strip() for k in sell_keywords_field.value.split(",") if k.strip()]
        settings_manager.set("custom_buy_keywords", buy_list)
        settings_manager.set("custom_sell_keywords", sell_list)
        page.show_dialog(ft.SnackBar(content=ft.Text("Settings saved successfully!")))
        close_settings(ev)
        refresh_callback()

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
                            content=ft.Column([api_id_field, api_hash_field, phone_field, symbol_suffix_field], spacing=10, scroll=ft.ScrollMode.ALWAYS),
                            padding=15,
                        ),
                        ft.Container(
                            content=ft.Column([openai_key_field, openai_model_field, min_confidence_field], spacing=10, scroll=ft.ScrollMode.ALWAYS),
                            padding=15,
                        ),
                        ft.Container(
                            content=ft.Column([time_filter_switch, ft.Row([time_from_field, time_to_field], spacing=10)], spacing=10, scroll=ft.ScrollMode.ALWAYS),
                            padding=15,
                        ),
                        ft.Container(
                            content=ft.Column([buy_keywords_field, sell_keywords_field], spacing=10, scroll=ft.ScrollMode.ALWAYS),
                            padding=15,
                        ),
                    ],
                ),
            ],
        ),
    )

    dlg = ft.AlertDialog(
        title=ft.Text("Settings"),
        content=ft.Container(content=tabs, width=550, height=400),
        actions=[
            ft.TextButton("Cancel", on_click=close_settings),
            ft.ElevatedButton("Save", bgcolor=SECONDARY, color="#121214", on_click=save_settings),
        ],
        actions_alignment=ft.MainAxisAlignment.END,
    )
    page.show_dialog(dlg)
