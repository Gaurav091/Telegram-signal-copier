"""Setup wizard shell — window frame, navigation, page orchestration."""
from __future__ import annotations

import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk

from telegram_signal_copier.setup.wizard_helpers import write_env
from telegram_signal_copier.setup.wizard_pages import AIPage, FinishPage
from telegram_signal_copier.setup.wizard_pages_core import (
    GroupsPage,
    MT5Page,
    TelegramPage,
    WelcomePage,
)


class SetupWizard(tk.Tk):
    _TITLE_BG = "#181825"
    _PAGE_BG = "#1e1e2e"
    _BTN_BG = "#313244"
    _ACCENT = "#89b4fa"

    def __init__(self) -> None:
        super().__init__()
        self.title("Telegram Signal Copier — Setup")
        self.resizable(False, False)
        self.configure(bg=self._TITLE_BG)
        self._center(520, 560)

        self._collected: dict[str, str] = {}
        self._pages: list[tk.Frame] = []
        self._current = 0
        self._env_path: Path | None = None

        self._build_header()
        self._build_body()
        self._build_footer()

        self._finish_page = FinishPage(self._body)
        pages_list = [
            WelcomePage(self._body),
            TelegramPage(self._body),
            MT5Page(self._body),
            GroupsPage(self._body),
            AIPage(self._body),
            self._finish_page,
        ]
        self._pages = pages_list
        self._show_page(0)

    def _center(self, w: int, h: int) -> None:
        self.update_idletasks()
        x = (self.winfo_screenwidth() - w) // 2
        y = (self.winfo_screenheight() - h) // 2
        self.geometry(f"{w}x{h}+{x}+{y}")

    def _build_header(self) -> None:
        hdr = tk.Frame(self, bg=self._TITLE_BG, height=64)
        hdr.pack(fill="x")
        hdr.pack_propagate(False)
        self._hdr_title = tk.Label(hdr, text="", font=("Segoe UI", 13, "bold"), bg=self._TITLE_BG, fg="#cdd6f4")
        self._hdr_title.pack(side="left", padx=20, pady=8)
        self._hdr_sub = tk.Label(hdr, text="", font=("Segoe UI", 9), bg=self._TITLE_BG, fg="#6c7086")
        self._hdr_sub.pack(side="left", padx=0, pady=8)

        self._step_frame = tk.Frame(self, bg=self._TITLE_BG)
        self._step_frame.pack(fill="x", padx=20)
        self._step_labels: list[tk.Label] = []
        page_names = ["Welcome", "Telegram", "MT5", "Groups", "AI / Volume", "Finish"]
        for i, name in enumerate(page_names):
            lbl = tk.Label(
                self._step_frame,
                text=f"{'●' if i == 0 else '○'} {name}",
                font=("Segoe UI", 8),
                bg=self._TITLE_BG,
                fg=self._ACCENT if i == 0 else "#45475a",
            )
            lbl.pack(side="left", padx=6, pady=2)
            self._step_labels.append(lbl)

        ttk.Separator(self, orient="horizontal").pack(fill="x")

    def _build_body(self) -> None:
        self._body = tk.Frame(self, bg=self._PAGE_BG)
        self._body.pack(fill="both", expand=True)

    def _build_footer(self) -> None:
        ttk.Separator(self, orient="horizontal").pack(fill="x")
        footer = tk.Frame(self, bg=self._TITLE_BG, height=52)
        footer.pack(fill="x")
        footer.pack_propagate(False)

        self._btn_next = tk.Button(
            footer, text="  Next  ›", font=("Segoe UI", 10, "bold"),
            bg=self._ACCENT, fg="#1e1e2e", relief="flat", bd=0, cursor="hand2", command=self._on_next,
        )
        self._btn_next.pack(side="right", padx=16, pady=10)

        self._btn_back = tk.Button(
            footer, text="‹  Back  ", font=("Segoe UI", 10),
            bg=self._BTN_BG, fg="#cdd6f4", relief="flat", bd=0, cursor="hand2", command=self._on_back,
        )
        self._btn_back.pack(side="right", padx=4, pady=10)

        self._step_info = tk.Label(footer, text="", font=("Segoe UI", 9), bg=self._TITLE_BG, fg="#6c7086")
        self._step_info.pack(side="left", padx=16)

    def _show_page(self, idx: int) -> None:
        if self._pages:
            for p in self._pages:
                p.pack_forget()

        page = self._pages[idx]
        page.pack(fill="both", expand=True)
        self._current = idx

        self._hdr_title.config(text=getattr(page, "title", ""))
        self._hdr_sub.config(text=getattr(page, "subtitle", ""))

        for i, lbl in enumerate(self._step_labels):
            name = lbl.cget("text").split(" ", 1)[1]
            if i < idx:
                lbl.config(text=f"✔ {name}", fg="#a6e3a1")
            elif i == idx:
                lbl.config(text=f"● {name}", fg=self._ACCENT)
            else:
                lbl.config(text=f"○ {name}", fg="#45475a")

        self._btn_back.config(state="normal" if idx > 0 else "disabled")
        total = len(self._pages)
        self._step_info.config(text=f"Step {idx + 1} of {total}")

        is_last = idx == total - 1
        self._btn_next.config(
            text="  Close  " if is_last else "  Next  ›",
            bg="#f38ba8" if is_last else self._ACCENT,
        )

    def _on_next(self) -> None:
        page = self._pages[self._current]
        err = page.validate() if hasattr(page, "validate") else None
        if err:
            messagebox.showerror("Validation Error", err, parent=self)
            return

        if hasattr(page, "collect"):
            self._collected.update(page.collect())

        next_idx = self._current + 1
        if next_idx >= len(self._pages):
            self.destroy()
            return

        # Before showing finish page: write .env
        if next_idx == len(self._pages) - 1:
            try:
                self._env_path = write_env(self._collected)
                self._finish_page.update_path(self._env_path)
            except Exception as exc:
                messagebox.showerror("Write Error", f"Could not save .env:\n{exc}", parent=self)
                return

        self._show_page(next_idx)

    def _on_back(self) -> None:
        if self._current > 0:
            self._show_page(self._current - 1)
