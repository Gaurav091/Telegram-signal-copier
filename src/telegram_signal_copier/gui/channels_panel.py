"""Channels panel — left sidebar with source list, search, toggle, and delete."""
from __future__ import annotations

import logging
from typing import Any

import flet as ft

from telegram_signal_copier.config import AppConfig
from telegram_signal_copier.config_helpers import _parse_source_spec
from telegram_signal_copier.gui.theme import (
    BADGE_BG,
    BG_PANEL,
    BORDER,
    ERROR,
    INPUT_BORDER,
    PRIMARY,
    SECONDARY,
    SUCCESS_TRACK,
    TEXT_PRIMARY,
    TEXT_SECONDARY,
)
from telegram_signal_copier.services.settings_manager import SettingsManager

logger = logging.getLogger(__name__)


class ChannelsPanel:
    """Left sidebar: channel/source list manager."""

    def __init__(self, page: ft.Page) -> None:
        self.page = page
        self.sidebar_channels = ft.Column(spacing=10)
        self.search_box = ft.TextField(
            hint_text="Search channels...",
            prefix_icon=ft.Icons.SEARCH,
            height=40,
            text_size=13,
            content_padding=10,
            border_color=INPUT_BORDER,
            on_change=self.on_search_channels,
        )
        self.sidebar_container = self._build_sidebar()

    def _build_sidebar(self) -> ft.Container:
        return ft.Container(
            content=ft.Column(
                [
                    ft.Text("SOURCES", size=13, color=TEXT_SECONDARY, weight=ft.FontWeight.W_600),
                    self.search_box,
                    ft.Divider(color=BORDER, height=10),
                    ft.Container(content=self.sidebar_channels, expand=True, padding=0),
                    ft.ElevatedButton(
                        "+ Add",
                        icon=ft.Icons.ADD,
                        color=PRIMARY,
                        bgcolor=BADGE_BG,
                        height=32,
                        style=ft.ButtonStyle(
                            shape=ft.RoundedRectangleBorder(radius=6),
                            text_style=ft.TextStyle(size=12),
                        ),
                        on_click=lambda e: self.on_add_channel_requested(),
                    ),
                ],
                spacing=10,
                scroll=ft.ScrollMode.AUTO,
            ),
            width=430,
            bgcolor=BG_PANEL,
            padding=ft.Padding.only(left=15, right=15, top=15, bottom=15),
            border=ft.Border.only(right=ft.BorderSide(1, BORDER)),
        )

    # ── Public API ─────────────────────────────────────────────────────────

    def refresh_channels_list(
        self,
        config: AppConfig,
        settings_manager: SettingsManager,
    ) -> None:
        """Reload channels configuration into the sidebar."""
        self.sidebar_channels.controls.clear()
        sources = config.telegram_source_mappings
        search_query = (self.search_box.value or "").lower()
        disabled_sources = settings_manager.get("disabled_sources", [])

        for label, identifier in sources:
            if search_query and search_query not in label.lower() and search_query not in identifier.lower():
                continue

            display_label = label[:42] + "..." if len(label) > 42 else label
            display_id = identifier[:30] + "..." if len(identifier) > 30 else identifier

            self.sidebar_channels.controls.append(
                ft.Container(
                    content=ft.Row(
                        [
                            ft.Column(
                                [
                                    ft.Text(display_label, size=13, weight=ft.FontWeight.W_600, color=TEXT_PRIMARY, max_lines=1, overflow=ft.TextOverflow.ELLIPSIS, width=220, tooltip=label),
                                    ft.Text(display_id, size=11, color=TEXT_SECONDARY),
                                ],
                                spacing=3,
                                expand=True,
                            ),
                            ft.Switch(
                                value=identifier not in disabled_sources,
                                active_color=SECONDARY,
                                active_track_color=SUCCESS_TRACK,
                                on_change=lambda e, lid=identifier: self.on_toggle_channel(lid, e.control.value, settings_manager),
                            ),
                            ft.IconButton(
                                icon=ft.Icons.DELETE_OUTLINE,
                                icon_color=ERROR,
                                icon_size=16,
                                padding=ft.Padding.symmetric(horizontal=4),
                                on_click=lambda e, lid=identifier: self.on_delete_channel(lid, settings_manager),
                            ),
                        ],
                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                        spacing=8,
                    ),
                    bgcolor="#1e1e24",
                    padding=12,
                    border_radius=6,
                    border=ft.Border.all(1, BORDER),
                )
            )
        self.page.update()

    # ── Event handlers (delegated to dashboard) ────────────────────────────

    def on_toggle_channel(self, identifier: str, is_enabled: bool, settings_manager: SettingsManager) -> None:
        disabled = settings_manager.get("disabled_sources", [])
        if is_enabled:
            if identifier in disabled:
                disabled.remove(identifier)
        else:
            if identifier not in disabled:
                disabled.append(identifier)
        settings_manager.set("disabled_sources", disabled)
        self.page.show_dialog(ft.SnackBar(content=ft.Text(f"Channel {'enabled' if is_enabled else 'disabled'} successfully")))

    def on_delete_channel(self, identifier: str, settings_manager: SettingsManager) -> None:
        sources: list[str] = settings_manager.get("telegram_sources", [])
        updated = [src for src in sources if _parse_source_spec(src)[1] != identifier]
        settings_manager.set("telegram_sources", updated)

    def on_search_channels(self, e: Any = None) -> None:
        # Handled by dashboard calling refresh_channels_list
        pass

    # ── Callback placeholder (set by dashboard) ────────────────────────────

    def on_add_channel_requested(self) -> None:
        """Override in dashboard to show add-channel dialog."""
        pass
