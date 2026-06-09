"""Launcher window — shown when .env already exists (double-click EXE)."""
from __future__ import annotations

import os
import subprocess
import sys
import threading
import tkinter as tk


class LauncherWindow(tk.Tk):
    """Compact launcher shown when config already exists."""

    def __init__(self) -> None:
        super().__init__()
        self.title("Telegram Signal Copier")
        self.resizable(False, False)
        self.configure(bg="#181825")
        self._status_var = tk.StringVar(value="")
        self._center(420, 350)
        self._build()

    def _center(self, w: int, h: int) -> None:
        self.update_idletasks()
        x = (self.winfo_screenwidth() - w) // 2
        y = (self.winfo_screenheight() - h) // 2
        self.geometry(f"{w}x{h}+{x}+{y}")

    def _build(self) -> None:
        tk.Label(
            self, text="🚀  Telegram Signal Copier",
            font=("Segoe UI", 16, "bold"), bg="#181825", fg="#cdd6f4",
        ).pack(pady=(30, 4))
        tk.Label(
            self, text="Configuration found. Ready to run.",
            font=("Segoe UI", 10), bg="#181825", fg="#6c7086",
        ).pack(pady=(0, 20))

        btn_frame = tk.Frame(self, bg="#181825")
        btn_frame.pack(pady=10)

        tk.Button(
            btn_frame, text=" Start Listener ", font=("Segoe UI", 12, "bold"),
            bg="#a6e3a1", fg="#1e1e2e", relief="flat", bd=0, cursor="hand2",
            command=self._start_listener,
        ).pack(side="left", padx=8)
        tk.Button(
            btn_frame, text=" Open Dashboard ", font=("Segoe UI", 12, "bold"),
            bg="#c5aae8", fg="#1e1e2e", relief="flat", bd=0, cursor="hand2",
            command=self._open_dashboard,
        ).pack(side="left", padx=8)
        tk.Button(
            btn_frame, text=" Re-run Setup ", font=("Segoe UI", 10),
            bg="#313244", fg="#cdd6f4", relief="flat", bd=0, cursor="hand2",
            command=self._rerun_setup,
        ).pack(side="left", padx=8)

        tk.Label(
            self, textvariable=self._status_var,
            font=("Segoe UI", 9, "italic"), bg="#181825", fg="#f9e2af",
        ).pack(pady=(15, 0))

    def _exe(self) -> str:
        return sys.executable

    def _start_listener(self) -> None:
        self._status_var.set("⏳  Starting listener…")
        def _do() -> None:
            try:
                exe = self._exe()
                args = [exe, "listen"] if getattr(sys, "frozen", False) else [exe, "-m", "telegram_signal_copier.main", "listen"]
                subprocess.Popen(args, creationflags=subprocess.CREATE_NEW_CONSOLE if os.name == "nt" else 0)
                self._status_var.set("✔  Listener started in a new window.")
            except Exception as exc:
                self._status_var.set(f"✖  Failed: {exc}")
        threading.Thread(target=_do, daemon=True).start()

    def _open_dashboard(self) -> None:
        self._status_var.set("⏳  Opening Dashboard…")
        def _do() -> None:
            try:
                exe = self._exe()
                args = [exe, "dashboard"] if getattr(sys, "frozen", False) else [exe, "-m", "telegram_signal_copier.main", "dashboard"]
                subprocess.Popen(args, creationflags=subprocess.CREATE_NEW_CONSOLE if os.name == "nt" else 0)
                self._status_var.set("✔  Dashboard opened.")
            except Exception as exc:
                self._status_var.set(f"✖  Failed: {exc}")
        threading.Thread(target=_do, daemon=True).start()

    def _rerun_setup(self) -> None:
        from telegram_signal_copier.setup.wizard_shell import SetupWizard
        self.destroy()
        wizard = SetupWizard()
        wizard.mainloop()
