"""Setup wizard pages — AI provider and Finish pages."""
from __future__ import annotations

import os
import subprocess
import sys
import threading
import tkinter as tk
from pathlib import Path

from telegram_signal_copier.setup.wizard_pages_core import _Page


class AIPage(_Page):
    title = "AI Provider  (optional)"
    subtitle = "An AI key improves signal parsing accuracy. You can skip this."

    def __init__(self, parent: tk.Widget) -> None:
        super().__init__(parent)
        self._key_var = tk.StringVar()
        self._vol_var = tk.StringVar(value="0.01")

        tk.Label(self, text="OpenAI-compatible API Key", font=("Segoe UI", 10, "bold"), bg="#1e1e2e", fg="#cdd6f4").pack(anchor="w", padx=30, pady=(20, 0))
        tk.Entry(
            self, textvariable=self._key_var, show="●", font=("Consolas", 10),
            bg="#313244", fg="#cdd6f4", insertbackground="#cdd6f4", relief="flat", bd=6, width=50,
        ).pack(fill="x", padx=30, pady=2)
        tk.Label(
            self, text="Leave blank to use heuristic-only parsing (still works well for standard signals).",
            font=("Segoe UI", 9), bg="#1e1e2e", fg="#6c7086", wraplength=460, justify="left",
        ).pack(anchor="w", padx=30)

        tk.Label(self, text="Default Trade Volume (lots)", font=("Segoe UI", 10, "bold"), bg="#1e1e2e", fg="#cdd6f4").pack(anchor="w", padx=30, pady=(20, 0))
        tk.Entry(
            self, textvariable=self._vol_var, font=("Consolas", 10),
            bg="#313244", fg="#cdd6f4", insertbackground="#cdd6f4", relief="flat", bd=6, width=12,
        ).pack(anchor="w", padx=30, pady=2)
        tk.Label(
            self, text="e.g. 0.01 = micro lot. Adjust to your account size and risk tolerance.",
            font=("Segoe UI", 9), bg="#1e1e2e", fg="#6c7086",
        ).pack(anchor="w", padx=30)

    def validate(self) -> str | None:
        vol = self._vol_var.get().strip()
        try:
            if float(vol) <= 0:
                raise ValueError
        except ValueError:
            return "Default Volume must be a positive number (e.g. 0.01)"
        return None

    def collect(self) -> dict[str, str]:
        return {
            "openai_api_key": self._key_var.get().strip(),
            "default_volume": self._vol_var.get().strip(),
        }


class FinishPage(_Page):
    title = "Ready to Launch"
    subtitle = "Your configuration has been saved."

    def __init__(self, parent: tk.Widget, env_path: Path | None = None) -> None:
        super().__init__(parent)
        self._env_path = env_path or Path("(not yet written)")
        self._status_var = tk.StringVar(value="")
        self._path_var = tk.StringVar(value=str(self._env_path))

        tk.Label(self, text="✔  Configuration saved to:", font=("Segoe UI", 11, "bold"), bg="#1e1e2e", fg="#a6e3a1").pack(anchor="w", padx=30, pady=(24, 2))
        tk.Label(self, textvariable=self._path_var, font=("Consolas", 9), bg="#1e1e2e", fg="#89b4fa", wraplength=460, justify="left").pack(anchor="w", padx=30)

        tk.Label(self, text="\nNext steps:", font=("Segoe UI", 11, "bold"), bg="#1e1e2e", fg="#cdd6f4").pack(anchor="w", padx=30)
        for s in [
            "1. Click  'Telegram Login'  below to authorise the app (one-time).",
            "2. Open MT5 and attach the  TelegramSignalCopierEA  to any chart.",
            "3. Click  'Start Listener'  to begin copying signals.",
        ]:
            tk.Label(self, text=s, font=("Segoe UI", 10), bg="#1e1e2e", fg="#cdd6f4", anchor="w", wraplength=460, justify="left").pack(anchor="w", padx=30, pady=2)

        tk.Label(self, textvariable=self._status_var, font=("Segoe UI", 10, "italic"), bg="#1e1e2e", fg="#f9e2af", wraplength=460, justify="left").pack(anchor="w", padx=30, pady=(12, 0))

        btn_row = tk.Frame(self, bg="#1e1e2e")
        btn_row.pack(anchor="w", padx=30, pady=(18, 0))
        self._login_btn = tk.Button(btn_row, text=" Telegram Login ", font=("Segoe UI", 11, "bold"), bg="#89b4fa", fg="#1e1e2e", relief="flat", bd=0, cursor="hand2", command=self._run_login)
        self._login_btn.pack(side="left", padx=(0, 10))
        self._listen_btn = tk.Button(btn_row, text=" Start Listener ", font=("Segoe UI", 11, "bold"), bg="#a6e3a1", fg="#1e1e2e", relief="flat", bd=0, cursor="hand2", command=self._run_listener)
        self._listen_btn.pack(side="left")
        self._dash_btn = tk.Button(btn_row, text=" Open Dashboard ", font=("Segoe UI", 11, "bold"), bg="#c5aae8", fg="#1e1e2e", relief="flat", bd=0, cursor="hand2", command=self._run_dashboard)
        self._dash_btn.pack(side="left", padx=(10, 0))

    def update_path(self, path: Path) -> None:
        self._env_path = path
        self._path_var.set(str(path))

    def _exe(self) -> str:
        return sys.executable

    def _run_login(self) -> None:
        self._status_var.set("⏳  Opening Telegram login… check the terminal window.")
        self._login_btn.config(state="disabled")
        def _do() -> None:
            try:
                exe = self._exe()
                args = [exe, "login"] if getattr(sys, "frozen", False) else [exe, "-m", "telegram_signal_copier.main", "login"]
                subprocess.Popen(args, creationflags=subprocess.CREATE_NEW_CONSOLE if os.name == "nt" else 0)
                self._status_var.set("✔  Login process launched in a new window.")
            except Exception as exc:
                self._status_var.set(f"✖  Failed to launch: {exc}")
            finally:
                self._login_btn.config(state="normal")
        threading.Thread(target=_do, daemon=True).start()

    def _run_listener(self) -> None:
        self._status_var.set("⏳  Starting listener…")
        self._listen_btn.config(state="disabled")
        def _do() -> None:
            try:
                exe = self._exe()
                args = [exe, "listen"] if getattr(sys, "frozen", False) else [exe, "-m", "telegram_signal_copier.main", "listen"]
                subprocess.Popen(args, creationflags=subprocess.CREATE_NEW_CONSOLE if os.name == "nt" else 0)
                self._status_var.set("✔  Listener started in a new window.")
            except Exception as exc:
                self._status_var.set(f"✖  Failed: {exc}")
            finally:
                self._listen_btn.config(state="normal")
        threading.Thread(target=_do, daemon=True).start()

    def _run_dashboard(self) -> None:
        self._status_var.set("⏳  Opening Dashboard…")
        self._dash_btn.config(state="disabled")
        def _do() -> None:
            try:
                exe = self._exe()
                args = [exe, "dashboard"] if getattr(sys, "frozen", False) else [exe, "-m", "telegram_signal_copier.main", "dashboard"]
                subprocess.Popen(args, creationflags=subprocess.CREATE_NEW_CONSOLE if os.name == "nt" else 0)
                self._status_var.set("✔  Dashboard opened.")
            except Exception as exc:
                self._status_var.set(f"✖  Failed: {exc}")
            finally:
                self._dash_btn.config(state="normal")
        threading.Thread(target=_do, daemon=True).start()
