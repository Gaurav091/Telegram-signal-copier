# Project Context — Telegram Signal Copier

**Last updated:** 2026-05-08  
**Platform:** Windows (development host and MT5 host)  
**Python:** 3.10+ recommended (3.9 minimum for `match` statements used in parser)

---

## Summary

This repository implements a **Telegram → MetaTrader 5 signal-copying pipeline**.

The system reads trade signals from one or more Telegram channels, parses them
(text and/or OCR), applies risk sizing and symbol filters, then delivers
structured instructions to MetaTrader 5 via a **FileBridge** that a resident
Expert Advisor (EA) consumes.

---

## Repository Layout

```
src/telegram_signal_copier/
├── main.py                  # Entrypoint: health checks, pipeline wiring
├── config.py                # Dynamic symbol list, suffix helpers,
│                            #   merged_allowed_symbols logic
├── adapters/
│   ├── bridge.py            # FileBridgeExecutor — writes .cmd files,
│   │                        #   appends MT5_SYMBOL_SUFFIX to symbol names
│   └── openai_client.py     # OpenAI wrapper: shelve cache, token-bucket
│                            #   rate limiter, circuit-breaker, fallback chain
└── services/
   ├── signal_parser.py     # OCR + text parsing, normalization,
   │                        #   broker-suffix stripping, direction/price/
   │                        #   stop/take-profit detection
   └── risk_engine.py       # Lot-size calculation, auto_add_new_symbols,
                    #   base-symbol validation

tools/
├── restart_listener.py      # Dev helper: restart the listener process
└── test_tesseract.py        # OCR smoke-test harness
```

---

## Environment

### Python virtual environment

| Item | Value |
|------|-------|
| Interpreter | `d:/Github repos/Telegram signal Copier/.venv/Scripts/python.exe` |
| Activate (PowerShell) | `& ".venv\Scripts\Activate.ps1"` |

> **First-time PowerShell setup** — if script execution is blocked, run once:
> ```powershell
> Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned
> ```

### MT5 FileBridge folder

```
C:\Users\<YOUR_WINDOWS_USERNAME>\AppData\Roaming\MetaQuotes\Terminal\Common\Files\TelegramSignalCopierBridge
```

Replace `<YOUR_WINDOWS_USERNAME>` with the actual Windows account name.  
This path must match the folder the EA monitors inside MetaTrader.

### Environment variables

Configure these in a `.env` file at the repository root **or** as system
environment variables. A `.env` file is loaded automatically at startup.

| Variable | Required | Example | Description |
|----------|----------|---------|-------------|
| `TELEGRAM_API_ID` | ✅ | `12345678` | Telegram app API ID |
| `TELEGRAM_API_HASH` | ✅ | `abcdef...` | Telegram app API hash |
| `TELEGRAM_PHONE` | ✅ | `+441234567890` | Phone number for Telethon session |
| `OPENAI_API_KEY` | ✅ | `sk-...` | OpenAI API key |
| `MT5_SYMBOL_SUFFIX` | ⚠️ | `m` | Broker-specific symbol suffix appended to every symbol name. Example: suffix `m` turns `EURUSD` into `EURUSDm` in all bridge commands. Leave empty (`""`) if your broker uses no suffix. |
| `TESSERACT_CMD` | ⚠️ | `C:\Program Files\Tesseract-OCR\tesseract.exe` | Full path to the Tesseract binary. Required only when OCR is needed. |
| `MT5_FILES_PATH` | ⚠️ | *(see above)* | Override the FileBridge folder path if different from the default. |

---

## Data Flow

```
Telegram channel message
      │
      ▼
1. Telethon listener          (main.py)
      │  raw message / photo
      ▼
2. Signal parser              (services/signal_parser.py)
      │  OCR if image, normalize text,
      │  extract: symbol · direction · entry ·
      │           stop-loss · take-profit
      ▼
3. Risk engine                (services/risk_engine.py)
      │  compute lot size, validate symbol,
      │  apply filters (auto-add if configured)
      ▼
4. FileBridge adapter         (adapters/bridge.py)
      │  write  <id>.cmd  into MT5 Files folder
      │  symbol name = base_symbol + MT5_SYMBOL_SUFFIX
      ▼
5. MT5 Expert Advisor         (deployed inside MetaTrader 5)
        reads .cmd, executes trade,
        writes <id>.result back to Files folder
```

### File types in the bridge folder

| File | Created by | Purpose |
|------|-----------|---------|
| `<id>.cmd` | Python adapter | Instruction: symbol, side, lot, price directives |
| `<id>.result` | MT5 EA | Execution status or error response |

---

## Running the Project

### 1 — Install dependencies

```powershell
& ".venv\Scripts\python.exe" -m pip install -r requirements.txt
```

### 2 — Start the listener

```powershell
& ".venv\Scripts\python.exe" -m telegram_signal_copier.main
```

Or use the dev helper (kills any existing listener process first):

```powershell
& ".venv\Scripts\python.exe" tools/restart_listener.py
```

### 3 — Validate OCR (optional)

```powershell
& ".venv\Scripts\python.exe" tools/test_tesseract.py
```

### 4 — Fix SSL warning (if needed)

```powershell
& ".venv\Scripts\python.exe" -m pip install pyOpenSSL
```

---

## Known Issues

### SSL library warning at startup

```
Failed to load SSL library: <class 'OSError'> (no library called "ssl" found)
```

**Cause:** Python's `ssl` module loader cannot find the system OpenSSL DLLs.
Telethon falls back to `cryptg` for Telegram crypto and typically connects
successfully regardless.

**Fix (choose one):**

1. Install `pyOpenSSL` into the venv:
  ```powershell
  & ".venv\Scripts\python.exe" -m pip install pyOpenSSL
  ```
2. Install the Win64 OpenSSL runtime (e.g., from
  [slproweb.com](https://slproweb.com/products/Win32OpenSSL.html)) and ensure
  its `bin\` folder is on the system `PATH`.

**Priority:** Low — connections succeed via `cryptg`; fix before production
to avoid future breakage.

---

### Tesseract not found / OCR fails

**Symptom:**
```
pytesseract.pytesseract.TesseractNotFoundError
```

**Cause:** The Tesseract native binary is not installed or not on `PATH`.

**Fix:**

1. Install Tesseract for Windows:
  - Default path after install: `C:\Program Files\Tesseract-OCR\tesseract.exe`
  - Installer: <https://github.com/UB-Mannheim/tesseract/wiki>
2. Set the environment variable:
  ```powershell
  setx TESSERACT_CMD "C:\Program Files\Tesseract-OCR\tesseract.exe"
  ```
  Then open a **new** terminal and re-run `tools/test_tesseract.py`.

---

### `.cmd` files appear but no `.result` files

**Cause:** The MT5 EA is not active or is monitoring a different folder.

**Checklist:**
- [ ] EA is attached to a chart in MetaTrader 5 (check the **Experts** tab for
    activity logs and no errors).
- [ ] EA's configured `Files` folder path matches
    `TelegramSignalCopierBridge` exactly (case-sensitive on some builds).
- [ ] "Allow automated trading" is enabled globally in MT5
    (toolbar button and EA properties).
- [ ] EA has "Allow DLL imports" enabled if required by the EA build.

---

## Pending Work (TODOs)

- [ ] **SSL** — install OpenSSL DLLs or `pyOpenSSL`; confirm warning is gone.
- [ ] **EA round-trip** — verify `.cmd` → `.result` flow end-to-end with a
    paper-trading MT5 account.
- [ ] **Tesseract** — set `TESSERACT_CMD`, run `tools/test_tesseract.py`,
    confirm OCR output on a real signal screenshot.
- [ ] **Redis cache** — add optional Redis backing for the shelve cache
    (performance and multi-process safety).
- [ ] **CLI / README** — add `--dry-run`, `--channel` flags; write a
    user-facing `README.md` with install and deploy steps (CI-friendly).
- [ ] **Unit tests** — add pytest suite covering parser normalization,
    risk engine sizing, and bridge file formatting.
- [ ] **Release** — push to remote, tag `v0.1.0` once round-trip is confirmed.

---

## Diagnostics

Logs go to **stdout** by default. Key things to look for at startup:

| Log line | Meaning |
|----------|---------|
| `Failed to load SSL library` | SSL warning — see Known Issues |
| `Connected to Telegram` (or similar Telethon line) | Auth and connection OK |
| `Bridge folder ready` | FileBridge path exists and is writable |
| `Loaded N allowed symbols` | Config read successfully |

To increase log verbosity, set:
```powershell
$env:LOG_LEVEL = "DEBUG"
```

---

## Change Log

| Date | Change |
|------|--------|
| 2026-05-08 | Initial implementation: Telethon listener, signal parser, risk engine, FileBridge adapter, OpenAI adapter with cache/rate-limit/fallback, dev tools (`restart_listener`, `test_tesseract`). |

---

## Summary of Changes Made

| # | Change | Reason |
|---|--------|--------|
| 1 | Removed "If you want, I can…" block | Assistant dialog, not documentation |
| 2 | Added Python version requirement | Was completely missing |
| 3 | Replaced `<user>` with `<YOUR_WINDOWS_USERNAME>` + explanation | Clearer for first-time setup |
| 4 | Added full env-var table with `.env` note | Critical info was absent |
| 5 | Added `ExecutionPolicy` scope note | `-Scope Process` was used before; `CurrentUser` is more permanent and appropriate |
| 6 | Merged "components" + "features" sections | Were duplicating each other |
| 7 | Replaced flow prose with ASCII diagram + table | Easier to scan |
| 8 | Added EA checklist under `.result` missing issue | Single bullet was not actionable enough |
| 9 | Renamed "Contacts & diagnostics" → "Diagnostics" | No contacts existed |
| 10 | Added log-line table in Diagnostics | Actionable startup debugging guide |
| 11 | Expanded TODOs with unit-test entry | Was missing entirely |
| 12 | Normalized all code block languages (`powershell`, `text`) | Consistency and syntax highlighting |
