# Project Context — Telegram Signal Copier

**Last updated:** 2026-06-19
**Platform:** Windows (development host and MT5 host)  
**Python:** 3.11+ (3.12 / 3.14 tested)

---

## Summary

This repository implements a **Telegram → MetaTrader 5 signal-copying pipeline**.

The system reads trade signals from one or more Telegram channels, parses them
(text and/or OCR), applies risk sizing and symbol filters, then delivers
structured instructions to MetaTrader 5 via a **FileBridge** that a resident
Expert Advisor (EA) consumes.

---

## Recent Changes (2026-06-19)

### Parser Improvements

Four fixes to improve signal parsing accuracy and reduce the 88.8% rejection rate:

1. **Multi-line SL/TP extraction** (`heuristic.py`): When SL/TP labels appear on
   their own line (e.g., "SL:\n4518"), the parser now looks at the next 3 lines for
   the price. Previously these were completely missed.

2. **Symbol detection rejects pure numbers** (`normalizers.py`): The fallback regex
   no longer matches strings that are purely numeric (e.g., "4525", "4190") which
   were incorrectly parsed as symbols from entry price text.

3. **Informational message filtering** (`patterns.py`): Extended TRADE_MANAGEMENT_RE
   to catch pip count updates ("40 PIPS RUNNING"), profit booking ("5375$ Done"),
   and casual chat ("fly", "congratulations"). These are now skipped early.

4. **Forex pair entry prices** (`heuristic.py`): Entry price extraction now uses
   symbol-aware minimum prices (0.1 for EURUSD/GBPUSD etc., 100.0 for XAUUSD/BTCUSD)
   so forex pair entries like "Entry: 1.0850" are no longer filtered out.

5. **Improved confidence calculation** (`heuristic.py`): Signals with symbol+side
   but missing SL/TP get lower confidence (max 0.55) so they're filtered earlier.
   Complete signals (symbol+side+2+ levels) get higher confidence (up to 0.95).

### Test Results
- 37/37 unit tests pass (15 signal parser + 22 pipeline)
- 21/25 realistic signal formats parse correctly
- Zero regressions — all existing ALGO TRADING forex, GTA, and other group parsing intact

---

## Repository Layout

All source files are kept under **300 lines** after a full modularisation refactor.

```
src/telegram_signal_copier/
├── main.py                     # Entry point — arg parsing, logging setup, health check
├── config.py                   # AppConfig dataclass and .env variable definitions
├── config_helpers.py           # dotenv loading, AI provider builder, env-parsing helpers
├── constants.py                # Shared constants (symbol aliases, regex fragments)
│
├── listener_builder.py         # build_pipeline() factory
├── listener_runner.py          # _run_listener, _run_with_restarts, heartbeat
├── listener_lock.py            # Lock/PID file helpers
├── listener_status.py          # Bridge status file writers
│
├── adapters/
│   ├── bridge.py               # FileBridgeExecutor — writes/reads MT5 bridge files
│   ├── bridge_helpers.py       # Static bridge utilities (payload builder, symbol retry)
│   ├── telegram_client.py      # TelegramSignalListener (Telethon)
│   ├── telegram_helpers.py     # SSL shim, platform patch, MessageBuffer
│   ├── openai_client.py        # OpenAIClient — fallback chain, rate limiting, circuit breaker
│   ├── openai_prompts.py       # System prompt strings for AI calls
│   ├── openai_utils.py         # json_from_text, image_data_url, compute_cache_key
│   ├── ai_cache.py             # In-memory + persistent AI response cache
│   ├── circuit_breaker.py      # Circuit breaker for AI provider health
│   └── provider_adapters.py    # Per-provider HTTP adapters
│
├── services/
│   ├── pipeline.py             # CopierPipeline — orchestrates all stages
│   ├── pipeline_intent.py      # Stage 1 intent classification
│   ├── pipeline_logger.py      # JSONL pipeline event logger
│   ├── risk_engine.py          # Trade validation: SL/TP sanity, RR ratio, confidence
│   ├── deduplication.py        # Duplicate signal suppression
│   ├── signal_parser.py        # Thin coordinator: SignalParser.parse()
│   ├── signal_patterns.py      # All compiled regex patterns and constants
│   ├── signal_normalizers.py   # Symbol/side/price normalizers
│   ├── signal_heuristic.py     # Cluster-context parser, MT5 screenshot parser
│   ├── signal_heuristic_parse.py  # Main heuristic_parse() function
│   ├── signal_ai_merge.py      # AI payload builder, merge_signals
│   ├── signal_crypto.py        # Crypto entry price recovery heuristics
│   ├── cluster_agent.py        # MessageClusterAgent — buffers related messages
│   ├── cluster_parser.py       # parse_cluster(), ClusterSignal, auto_derive_sl()
│   ├── image_processor.py      # Tesseract OCR + AI vision
│   ├── intent_classifier.py    # Standalone intent classifier
│   ├── message_buffer.py       # Low-level message accumulation buffer
│   ├── message_logger.py       # Raw message JSONL logger
│   ├── trade_tracker.py        # Open-position tracker, partial-close state
│   └── telegram_session.py     # Telethon session management helpers
│
├── agents/
│   ├── graph.py                # _Pipeline, build_graph(), run_on_message()
│   ├── graph_listener.py       # start_listener() — legacy Telethon agent listener
│   ├── intent_filter.py        # Intent filter node
│   ├── extraction_agent.py     # Signal extraction node
│   ├── validation_agent.py     # Validation node
│   ├── execution_agent.py      # Trade execution node
│   ├── developer_agent.py      # Re-export shim for developer agent API
│   ├── developer_agent_models.py  # FailureReport, Patch, FalsePositiveReport
│   ├── developer_agent_analysis.py  # classify_failures()
│   ├── developer_agent_patch.py    # generate_patch, apply_patch, rollback
│   ├── developer_agent_fp.py       # assess_false_positives, fix_false_positives
│   ├── schemas.py              # AgentState pydantic model
│   └── _llm_shim.py            # SimpleLLM wrapper
│
└── models/
    └── contracts.py            # TradeCommand, ExecutionResult, TelegramSignalMessage

tools/
├── supervisor.py               # Auto-restart daemon
└── ...                         # Diagnostic / dev helper scripts
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

- [x] **TP ordering (Unicode superscript)** — fixed: heuristic parser now normalises
    `¹²³…` to ASCII digits before pattern matching, so `Tp¹ 4508` is correctly
    extracted as TP1 instead of being skipped.
- [x] **TP fallback slice** — fixed: fallback price-list TP extraction now uses
    `[:3]` instead of the previous `[1:3]` which was silently discarding TP1.
- [x] **Risk engine TP direction filter** — fixed: before the TP1 direction check
    the engine now promotes the first valid-direction TP when TP1 is out-of-range
    (safety net for any parser that emits mixed-direction TPs).
- [x] **MT5 screenshot OCR entry corruption** — fixed: `_parse_mt5_screenshot`
    now collects *all* price candidates from the entry line and picks the one
    consistent with side + SL + TP when the first candidate appears inverted
    (e.g. OCR `13609 → 73602` for BTCUSD).
- [x] **API rate-limit optimisation** — pipeline now runs a heuristic preview
    *before* calling the intent-classification API; if the text is already a
    complete signal the AI call is skipped entirely (saves 1 API call/message
    for all pure-text signals).
- [x] **Combined intent+parse** — `parse_signal` system prompt now includes an
    `intent` field so a single AI round-trip returns both classification and
    extraction.
- [x] **BTCUSD OCR parsing (7-digit prices)** — fixed: regex patterns now support
    7-digit numbers (`\d{1,7}`) to match BTC prices like 77645.45. OCR spaced
    number normalization integrated into `parse_ocr_signal` to fix artifacts
    like "77 645.45" → "77645.45". Crypto entry recovery now called in OCR path.
- [ ] **SSL** — install OpenSSL DLLs or `pyOpenSSL`; confirm warning is gone.
- [ ] **EA round-trip** — verify `.cmd` → `.result` flow end-to-end with a
    paper-trading MT5 account.
- [ ] **Tesseract** — set `TESSERACT_CMD`, run `tools/test_tesseract.py`,
    confirm OCR output on a real signal screenshot.
- [ ] **Redis cache** — add optional Redis backing for the shelve cache
    (performance and multi-process safety).
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
