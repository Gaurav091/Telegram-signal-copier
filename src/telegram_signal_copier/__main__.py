import os
import sys
from pathlib import Path


def _env_exists() -> bool:
    """Check if a .env file exists in the expected config directory."""
    override = os.environ.get("TELEGRAM_SIGNAL_COPIER_HOME", "")
    if override:
        return (Path(override) / ".env").exists()
    if getattr(sys, "frozen", False):
        return (Path(os.environ.get("APPDATA", str(Path.home()))) / "TelegramSignalCopier" / ".env").exists()
    # Dev mode - project root
    return (Path(__file__).resolve().parents[3] / ".env").exists()


if __name__ == "__main__":
    no_args = len(sys.argv) <= 1
    explicit_setup = len(sys.argv) > 1 and sys.argv[1] == "setup"

    if explicit_setup:
        # Always show full wizard when "setup" is passed
        from telegram_signal_copier.setup_wizard import run_wizard
        run_wizard()
    elif no_args and getattr(sys, "frozen", False):
        # Double-clicked frozen EXE: show GUI launcher/wizard
        if _env_exists():
            from telegram_signal_copier.setup_wizard import run_launcher
            run_launcher()
        else:
            from telegram_signal_copier.setup_wizard import run_wizard
            run_wizard()
    elif no_args and not _env_exists():
        # Dev mode, no .env yet
        from telegram_signal_copier.setup_wizard import run_wizard
        run_wizard()
    else:
        from telegram_signal_copier.main import main
        main()