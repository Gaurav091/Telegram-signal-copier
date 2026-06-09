"""GUI theme constants and Flet page setup helpers."""
from __future__ import annotations

import flet as ft

# ── Color palette ────────────────────────────────────────────────────────────
PRIMARY = "#00e5ff"       # Neon Cyan
SECONDARY = "#00e676"     # Mint Green
ERROR = "#ff1744"         # Red
WARNING = "#ffb300"       # Amber
SURFACE = "#1e1e24"       # Card background
BG_DARK = "#121214"       # Page background
BG_PANEL = "#16161a"      # Sidebar / panel background
BORDER = "#26262b"        # Border color
INPUT_BORDER = "#36363b"  # Input field border
TEXT_PRIMARY = "#ffffff"
TEXT_SECONDARY = "#7c7c82"
BADGE_BG = "#1a3238"      # Badge / tag background
SUCCESS_TRACK = "#1a3828" # Switch active track


def build_theme() -> ft.Theme:
    """Return the app-wide Flet Theme with custom color scheme."""
    return ft.Theme(
        color_scheme=ft.ColorScheme(
            primary=PRIMARY,
            secondary=SECONDARY,
            surface=SURFACE,
            error=ERROR,
        )
    )


def setup_page_properties(page: ft.Page) -> None:
    """Configure page title, size, colors, and theme."""
    page.title = "✦ Telegram Signal Copier - Dashboard"
    page.theme_mode = ft.ThemeMode.DARK
    page.bgcolor = BG_DARK
    page.window.width = 1200
    page.window.height = 750
    page.window.resizable = True
    page.padding = 0
    page.theme = build_theme()
