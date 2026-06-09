"""Setup wizard core pages — Welcome, Telegram, MT5, Groups."""
from __future__ import annotations

import threading
import tkinter as tk

from telegram_signal_copier.setup.wizard_helpers import open_url


class _Page(tk.Frame):
    """Base class for a wizard page."""

    title: str = ""
    subtitle: str = ""

    def __init__(self, parent: tk.Widget) -> None:
        super().__init__(parent, bg="#1e1e2e")

    def validate(self) -> str | None:
        return None

    def collect(self) -> dict[str, str]:
        return {}


class WelcomePage(_Page):
    title = "Welcome to Telegram Signal Copier"
    subtitle = "This wizard will configure the app in a few quick steps."

    def __init__(self, parent: tk.Widget) -> None:
        super().__init__(parent)
        tk.Label(
            self, text="📋  What you'll need:",
            font=("Segoe UI", 11, "bold"), bg="#1e1e2e", fg="#cdd6f4",
        ).pack(anchor="w", pady=(20, 6), padx=30)

        items = [
            ("Telegram API credentials", "Get a free API ID + Hash from  my.telegram.org → 'API development tools'"),
            ("Your MT5 account details", "Account number, password and broker server name (e.g. Exness-MT5Real8)"),
            ("Telegram group names", "Names of the signal channels you want to copy trades from"),
            ("(Optional) AI API key", "SambaNova / Groq / OpenAI key for smarter signal parsing"),
        ]
        for heading, detail in items:
            row = tk.Frame(self, bg="#1e1e2e")
            row.pack(fill="x", padx=30, pady=3)
            tk.Label(row, text="✔  ", font=("Segoe UI", 10), bg="#1e1e2e", fg="#a6e3a1").pack(side="left")
            col = tk.Frame(row, bg="#1e1e2e")
            col.pack(side="left", fill="x")
            tk.Label(col, text=heading, font=("Segoe UI", 10, "bold"), bg="#1e1e2e", fg="#cdd6f4", anchor="w").pack(anchor="w")
            tk.Label(col, text=detail, font=("Segoe UI", 9), bg="#1e1e2e", fg="#6c7086", anchor="w", wraplength=440, justify="left").pack(anchor="w")

        tk.Label(
            self, text="Click  Next  to begin.",
            font=("Segoe UI", 10, "italic"), bg="#1e1e2e", fg="#89b4fa",
        ).pack(pady=20)


class TelegramPage(_Page):
    title = "Telegram Connection"
    subtitle = "Your Telegram API credentials and phone number."

    def __init__(self, parent: tk.Widget) -> None:
        super().__init__(parent)
        self._vars: dict[str, tk.StringVar] = {}
        fields = [
            ("Phone Number", "telegram_phone", "+1234567890", False, "International format, e.g. +447911123456"),
            ("API ID", "telegram_api_id", "", False, "From my.telegram.org → API development tools"),
            ("API Hash", "telegram_api_hash", "", False, "32-character string from my.telegram.org"),
        ]
        for label, key, placeholder, secret, hint in fields:
            self._add_field(label, key, placeholder, secret, hint)

        _link = tk.Label(
            self, text="Open my.telegram.org  ↗",
            font=("Segoe UI", 9, "underline"), bg="#1e1e2e", fg="#89b4fa", cursor="hand2",
        )
        _link.pack(anchor="w", padx=30, pady=(4, 0))
        _link.bind("<Button-1>", lambda _: open_url("https://my.telegram.org/apps"))

    def _add_field(self, label: str, key: str, placeholder: str, secret: bool, hint: str) -> None:
        var = tk.StringVar(value=placeholder if placeholder and not placeholder.startswith("+") else "")
        if placeholder.startswith("+"):
            var.set(placeholder)
        self._vars[key] = var
        frame = tk.Frame(self, bg="#1e1e2e")
        frame.pack(fill="x", padx=30, pady=(10, 0))
        tk.Label(frame, text=label, font=("Segoe UI", 10, "bold"), bg="#1e1e2e", fg="#cdd6f4", anchor="w").pack(anchor="w")
        entry = tk.Entry(
            frame, textvariable=var, show="●" if secret else "",
            font=("Consolas", 10), bg="#313244", fg="#cdd6f4",
            insertbackground="#cdd6f4", relief="flat", bd=6, width=46,
        )
        entry.pack(fill="x", pady=2)
        if hint:
            tk.Label(frame, text=hint, font=("Segoe UI", 8), bg="#1e1e2e", fg="#6c7086", anchor="w").pack(anchor="w")

    def validate(self) -> str | None:
        phone = self._vars["telegram_phone"].get().strip()
        api_id = self._vars["telegram_api_id"].get().strip()
        api_hash = self._vars["telegram_api_hash"].get().strip()
        if not phone or not phone.startswith("+"):
            return "Phone number must start with + and country code (e.g. +44…)"
        if not api_id.isdigit():
            return "API ID must be a number from my.telegram.org"
        if len(api_hash) < 20:
            return "API Hash looks too short — copy the full 32-character string"
        return None

    def collect(self) -> dict[str, str]:
        return {k: v.get().strip() for k, v in self._vars.items()}


class MT5Page(_Page):
    title = "MT5 Account"
    subtitle = "Your MetaTrader 5 account credentials."

    def __init__(self, parent: tk.Widget) -> None:
        super().__init__(parent)
        self._vars: dict[str, tk.StringVar] = {}
        fields = [
            ("Account Login (number)", "mt5_login", "", False, "Your MT5 account number, e.g. 272489632"),
            ("Password", "mt5_password", "", True, "MT5 investor or master password"),
            ("Broker Server", "mt5_server", "", False, "Server name shown in MT5 login screen, e.g. Exness-MT5Real8"),
            ("Broker Symbol Suffix (optional)", "mt5_symbol_suffix", "", False, "Suffix if required by broker, e.g. 'm' for XAUUSDm"),
        ]
        for label, key, placeholder, secret, hint in fields:
            self._add_field(label, key, placeholder, secret, hint)

        tk.Label(
            self,
            text="⚠  MetaTrader 5 must be installed and running on this machine.\n"
                 "   Attach the TelegramSignalCopierEA Expert Advisor to any chart.",
            font=("Segoe UI", 9), bg="#1e1e2e", fg="#f38ba8", justify="left",
        ).pack(anchor="w", padx=30, pady=(18, 0))

    def _add_field(self, label: str, key: str, placeholder: str, secret: bool, hint: str) -> None:
        var = tk.StringVar()
        self._vars[key] = var
        frame = tk.Frame(self, bg="#1e1e2e")
        frame.pack(fill="x", padx=30, pady=(10, 0))
        tk.Label(frame, text=label, font=("Segoe UI", 10, "bold"), bg="#1e1e2e", fg="#cdd6f4", anchor="w").pack(anchor="w")
        entry = tk.Entry(
            frame, textvariable=var, show="●" if secret else "",
            font=("Consolas", 10), bg="#313244", fg="#cdd6f4",
            insertbackground="#cdd6f4", relief="flat", bd=6, width=46,
        )
        entry.pack(fill="x", pady=2)
        if hint:
            tk.Label(frame, text=hint, font=("Segoe UI", 8), bg="#1e1e2e", fg="#6c7086", anchor="w").pack(anchor="w")

    def validate(self) -> str | None:
        login_str = self._vars["mt5_login"].get().strip()
        password = self._vars["mt5_password"].get().strip()
        server = self._vars["mt5_server"].get().strip()
        if not login_str.isdigit():
            return "MT5 Account Login must be a number"
        if not server:
            return "Broker Server is required (check your MT5 login screen)"

        try:
            import MetaTrader5 as mt5
        except ImportError:
            return None

        progress = tk.Toplevel(self)
        progress.title("Verifying...")
        progress.configure(bg="#1e1e2e")
        progress.resizable(False, False)
        progress.transient(self)
        progress.grab_set()

        w, h = 320, 120
        parent_x = self.winfo_toplevel().winfo_x()
        parent_y = self.winfo_toplevel().winfo_y()
        progress.geometry(f"{w}x{h}+{parent_x + 100}+{parent_y + 180}")

        tk.Label(
            progress,
            text="Connecting to MetaTrader 5...\nPlease make sure MT5 terminal is running.",
            font=("Segoe UI", 10), bg="#1e1e2e", fg="#cdd6f4",
            wraplength=280, justify="center", pady=15,
        ).pack(fill="both", expand=True)

        result_err: list[str | None] = []

        def run_check() -> None:
            try:
                login_val = int(login_str)
                if not mt5.initialize(login=login_val, password=password, server=server):
                    err_code, err_desc = mt5.last_error()
                    result_err.append(f"Initialization failed (Code {err_code}): {err_desc}\nMake sure MetaTrader 5 terminal is installed and active.")
                    return
                acc_info = mt5.account_info()
                if acc_info is None:
                    err_code, err_desc = mt5.last_error()
                    result_err.append(f"Credentials rejected by server (Code {err_code}): {err_desc}")
                else:
                    result_err.append(None)
            except Exception as e:
                result_err.append(f"Verification error: {e}")
            finally:
                mt5.shutdown()
                try:
                    progress.destroy()
                except Exception:
                    pass

        t = threading.Thread(target=run_check, daemon=True)
        t.start()
        self.wait_window(progress)

        if result_err and result_err[0] is not None:
            return result_err[0]
        return None

    def collect(self) -> dict[str, str]:
        return {k: v.get().strip() for k, v in self._vars.items()}


class GroupsPage(_Page):
    title = "Signal Groups"
    subtitle = "Add the Telegram channels you want to copy signals from."

    def __init__(self, parent: tk.Widget) -> None:
        super().__init__(parent)
        self._groups: list[str] = []

        tk.Label(
            self,
            text="Type the exact channel name as it appears in Telegram, then click  Add.",
            font=("Segoe UI", 9), bg="#1e1e2e", fg="#6c7086", wraplength=460, justify="left",
        ).pack(anchor="w", padx=30, pady=(14, 6))

        row = tk.Frame(self, bg="#1e1e2e")
        row.pack(fill="x", padx=30)
        self._entry_var = tk.StringVar()
        entry = tk.Entry(
            row, textvariable=self._entry_var, font=("Segoe UI", 10),
            bg="#313244", fg="#cdd6f4", insertbackground="#cdd6f4",
            relief="flat", bd=6, width=38,
        )
        entry.pack(side="left", fill="x", expand=True, pady=2)
        entry.bind("<Return>", lambda _: self._add())
        tk.Button(
            row, text=" + Add ", font=("Segoe UI", 10, "bold"),
            bg="#89b4fa", fg="#1e1e2e", relief="flat", bd=0, cursor="hand2", command=self._add,
        ).pack(side="left", padx=(6, 0))

        list_frame = tk.Frame(self, bg="#1e1e2e")
        list_frame.pack(fill="both", expand=True, padx=30, pady=(8, 0))
        scrollbar = tk.Scrollbar(list_frame, orient="vertical")
        self._listbox = tk.Listbox(
            list_frame, font=("Segoe UI", 10), bg="#313244", fg="#cdd6f4",
            selectbackground="#89b4fa", selectforeground="#1e1e2e",
            relief="flat", bd=0, activestyle="none",
            yscrollcommand=scrollbar.set, height=6,
        )
        scrollbar.config(command=self._listbox.yview)
        scrollbar.pack(side="right", fill="y")
        self._listbox.pack(fill="both", expand=True)

        tk.Button(
            self, text=" ✕ Remove selected ", font=("Segoe UI", 9),
            bg="#f38ba8", fg="#1e1e2e", relief="flat", bd=0, cursor="hand2", command=self._remove,
        ).pack(anchor="e", padx=30, pady=(4, 0))

    def _add(self) -> None:
        name = self._entry_var.get().strip()
        if name and name not in self._groups:
            self._groups.append(name)
            self._listbox.insert(tk.END, name)
            self._entry_var.set("")

    def _remove(self) -> None:
        sel = self._listbox.curselection()
        if sel:
            idx = sel[0]
            self._groups.pop(idx)
            self._listbox.delete(idx)

    def validate(self) -> str | None:
        if not self._groups:
            return "Add at least one Telegram signal group"
        return None

    def collect(self) -> dict[str, str]:
        return {"telegram_sources": ",".join(self._groups)}
