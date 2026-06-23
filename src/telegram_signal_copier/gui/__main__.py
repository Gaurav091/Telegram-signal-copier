"""Allow running GUI via `python -m telegram_signal_copier.gui`."""
import flet as ft

from telegram_signal_copier.gui.dashboard import SignalCopierDashboard


def main(page: ft.Page) -> None:
    SignalCopierDashboard(page)


if __name__ == "__main__":
    ft.run(main)
