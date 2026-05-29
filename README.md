# Telegram Signal Copier

A production-ready trading automation system that monitors Telegram signal groups, uses AI + OCR to parse trade signals from text and images, and executes them automatically in MetaTrader 5 through a file-bridge Expert Advisor.

---

## Table of Contents

1. [Architecture Overview](#architecture-overview)
2. [Prerequisites](#prerequisites)
3. [Installation](#installation)
4. [Windows EXE / Installer Build](#windows-exe--installer-build)
5. [Configuration (.env)](#configuration-env)
6. [MT5 Expert Advisor Setup](#mt5-expert-advisor-setup)
7. [Running the Listener](#running-the-listener)
8. [How Signals Are Processed](#how-signals-are-processed)
9. [Supported Signal Formats](#supported-signal-formats)
10. [Troubleshooting](#troubleshooting)
11. [Key Files Reference](#key-files-reference)

---

## Architecture Overview

```text
Telegram Groups / Channels
        │
        ▼
  Python Listener (Telethon)
        │  raw messages + images
        ▼
  Message Cluster Agent          ← buffers & groups related messages
        │
        ▼
  Signal Pipeline
  ├── Stage 1: Intent filter     ← skips P&L updates, news, non-trades
  ├── Stage 2: Heuristic parse   ← fast regex-based extraction
  ├── Stage 3: OCR (Tesseract)   ← extracts text from chart images
  ├── Stage 4: AI parse          ← OpenAI / Cloudflare / Groq vision
  └── Stage 5: Risk engine       ← validates SL/TP/confidence/symbol
        │
        ▼
  MT5 File Bridge
  ├── bridge_root/               ← command files written here
  │   ├── <request_id>.txt       ← key=value trade command
  │   ├── command_queue.txt      ← EA reads this list
  │   └── outbox/<id>.result     ← EA writes result here
        │
        ▼
  TelegramSignalCopierEA (MT5)   ← polls bridge, places orders, writes result
```

---

## Prerequisites

| Requirement | Version | Notes |
|---|---|---|
| Python | 3.11+ | 3.12 / 3.14 tested |
| MetaTrader 5 | Any | Exness, ICMarkets, etc. |
| MetaEditor 64 | Bundled with MT5 | For compiling the EA |
| Tesseract OCR | 5.x | Windows: [UB Mannheim build](https://github.com/UB-Mannheim/tesseract/wiki) |
| OpenSSL runtime (Windows) | 4.x | Recommended to avoid Telethon SSL loader warning |
| Git | Any | For cloning |

**AI provider** (at least one required for image signals):
- OpenAI API key (`gpt-4o-mini` or better with vision)
- Or any compatible alternative: Cloudflare AI, NVIDIA NIM, Cerebras, Groq

---

## Installation

```bash
# 1. Clone the repository
git clone https://github.com/Gaurav091/Telegram-signal-copier.git
cd "Telegram-signal-copier"

# 2. Create and activate virtual environment
python -m venv .venv
# Windows:
.venv\Scripts\activate
# Linux/macOS:
source .venv/bin/activate

# 3. Install all dependencies
pip install -e ".[telegram,agents,dev]"

# 4. Install Tesseract OCR (Windows)
#    Download from: https://github.com/UB-Mannheim/tesseract/wiki
#    Install to default path: C:\Program Files\Tesseract-OCR\tesseract.exe
```

---

## Windows EXE / Installer Build

You can build a self-contained Windows app bundle and, optionally, an installer EXE.

### Outputs

- `dist\TelegramSignalCopier\TelegramSignalCopier.exe`
- `dist\installer\TelegramSignalCopier-Setup.exe` if Inno Setup 6 is installed

### Installed runtime path

Packaged builds store writable runtime data here:

```text
%APPDATA%\TelegramSignalCopier
```

That folder holds:

- `.env`
- `.env.example`
- `logs\`
- `runtime\sessions\`
- `runtime\media\`
- `ai_cache.db`

Override it with:

```env
TELEGRAM_SIGNAL_COPIER_HOME=C:\TelegramSignalCopierData
```

### Target-machine prerequisites

- MetaTrader 5 still required for live execution
- Tesseract still required for OCR/image parsing
- Inno Setup 6 only required on the build machine if you want an installer EXE

### Build

```powershell
.venv\Scripts\Activate.ps1
powershell -ExecutionPolicy Bypass -File packaging\build_windows_bundle.ps1
```

Optional:

```powershell
powershell -ExecutionPolicy Bypass -File packaging\build_windows_bundle.ps1 -Clean
powershell -ExecutionPolicy Bypass -File packaging\build_windows_bundle.ps1 -SkipInstaller
```

### After install

1. Edit `%APPDATA%\TelegramSignalCopier\.env`
2. Install Tesseract if you need OCR/image parsing
3. Copy and compile `TelegramSignalCopierEA.mq5` into MT5
4. Run the login shortcut once
5. Run the listener shortcut

---

## Configuration (.env)

Copy the template below and save it as `.env` in the project root:

```env
# ─── Telegram ────────────────────────────────────────────────────────────────
# Get API credentials from https://my.telegram.org → API development tools
TELEGRAM_API_ID=12345678
TELEGRAM_API_HASH=abcdef1234567890abcdef1234567890
TELEGRAM_PHONE_NUMBER=+1234567890
TELEGRAM_SESSION_NAME=telegram-signal-copier

# Comma-separated group/channel names or IDs to monitor
# Use the exact group name visible in Telegram, or the numeric chat ID
TELEGRAM_SOURCES=GOLD VIP SIGNALS,ALGO TRADING forex.,XAUUSD GOLD SIGNAL

# ─── AI Provider (at least one required for image signals) ───────────────────
# OpenAI (primary) — supports vision models
OPENAI_API_KEY=sk-...
OPENAI_MODEL=gpt-4o-mini
OPENAI_BASE_URL=https://api.openai.com/v1

# Optional fallback providers (tried in order if primary fails)
# CLOUDFLARE_ACCOUNT_ID=
# CLOUDFLARE_API_TOKEN=
# NVIDIA_API_KEY=
# CEREBRAS_API_KEY=
# GROQ_API_KEY=

# ─── MT5 Bridge ──────────────────────────────────────────────────────────────
# Path to MetaTrader 5 Common Files folder (shared with all MT5 terminals)
# Default auto-detected on Windows. Override only if non-standard install.
# MT5_BRIDGE_DIR=C:\Users\YourName\AppData\Roaming\MetaQuotes\Terminal\Common\Files\TelegramSignalCopierBridge

# Broker symbol suffix — e.g. "m" for XAUUSDm, leave blank if none
MT5_SYMBOL_SUFFIX=m

# How long (seconds) to wait for the EA to return a result
MT5_BRIDGE_TIMEOUT_SECONDS=60

# ─── Trading Parameters ──────────────────────────────────────────────────────
# Default lot size for all trades
DEFAULT_VOLUME=0.01

# Minimum AI confidence to auto-approve (0.0–1.0)
MINIMUM_CONFIDENCE=0.45

# Signals below this confidence require manual review
APPROVAL_REQUIRED_BELOW=0.45

# Comma-separated list of allowed symbols (EA will also enforce this)
ALLOWED_SYMBOLS=XAUUSD,EURUSD,GBPUSD,USDJPY,BTCUSD,ETHUSD,XAGUSD,US30,NAS100,USOIL,SPX500

# Set to true to parse signals without placing real trades
DRY_RUN=false

# Minimum reward-to-risk ratio (0 = disabled)
MINIMUM_RR_RATIO=0
```

### First-time Telegram authentication

On the first run, Telethon will prompt for your phone number and the OTP code sent by Telegram. After successful login a `.session` file is saved so you won't be prompted again.

```bash
python -m telegram_signal_copier
```

---

## MT5 Expert Advisor Setup

The EA reads trade commands from the bridge files and places orders inside MT5.

### Step 1 — Compile the EA

```powershell
# Copy source to MT5 Experts folder and compile
$mt5_ea_dir = "$env:APPDATA\MetaQuotes\Terminal\<YOUR_TERMINAL_ID>\MQL5\Experts\Advisors"
Copy-Item "mt5\Experts\TelegramSignalCopierEA.mq5" "$mt5_ea_dir\" -Force

# Open MetaEditor and press F7, or use command line:
& "C:\Program Files\MetaTrader 5 EXNESS\metaeditor64.exe" /compile:"$mt5_ea_dir\TelegramSignalCopierEA.mq5"
```

> **Tip:** Find your `<YOUR_TERMINAL_ID>` by opening MetaTrader 5 → File → Open Data Folder.

### Step 2 — Attach to a chart

1. Open MetaTrader 5
2. Open a chart for your main symbol (e.g. **XAUUSDm M1**)
3. In the Navigator panel → Expert Advisors → drag **TelegramSignalCopierEA** onto the chart
4. Enable **Allow Algo Trading** in the EA dialog
5. Click the **AutoTrading** toolbar button (must show green)

### Step 3 — EA input parameters

| Parameter | Default | Description |
|---|---|---|
| `BridgeFolderName` | `TelegramSignalCopierBridge` | Must match the folder in Common Files |
| `MagicNumber` | `20260001` | Unique tag for all positions opened by this EA — prevents other EAs from closing them |
| `MaxSlippagePoints` | `30` | Maximum allowed slippage |
| `MaxCommandAgeSeconds` | `180` | Commands older than this are rejected |
| `AllowedSymbols` | *(list)* | Comma-separated symbols the EA will trade |
| `AllowMarketOrders` | `true` | Allow/block market orders |
| `AllowPendingOrders` | `true` | Allow/block pending orders |
| `TimerIntervalSeconds` | `1` | How often the EA checks for new commands |

### Step 4 — Verify the bridge is working

The EA chart comment will show live listener status. You should see:
```
Telegram Signal Copier EA
Bridge: TelegramSignalCopierBridge
Telegram: CONNECTED (running)
Account: @YourHandle
Heartbeat: 2026-05-19 ...
```

---

## Running the Listener

```bash
# Activate venv first
.venv\Scripts\activate   # Windows
source .venv/bin/activate  # Linux/macOS

# Start the listener (blocks, run in a terminal or as a service)
python -m telegram_signal_copier

# Or use the installed script entry point
telegram-signal-copier
```

The listener will:
1. Connect to Telegram
2. Join / monitor all groups in `TELEGRAM_SOURCES`
3. Process every incoming message through the pipeline
4. Send approved trades to the MT5 bridge
5. Write status to `TelegramSignalCopierBridge/telegram_status.txt` (visible on the EA chart)

### Keeping it running (Windows — optional)

Use the included supervisor script to auto-restart on crashes:

```powershell
python tools\supervisor.py
```

---

## How Signals Are Processed

```
Message received
  └─ Intent filter (is this a trade signal?)
       ├─ SHORTCUT → text-only + heuristic complete → skip AI intent call entirely
       ├─ SKIPPED  → informational / news / emoji-only
       ├─ SKIPPED  → trade update (P&L screenshot) unless "New"/"Both New" caption
       └─ CONTINUE
            └─ Heuristic parser (fast regex, no AI)
                 └─ Complete? ──Yes──▶ execute (0 AI calls for pure-text signals)
                              └─No─▶ OCR image (Tesseract)
                                       └─ AI vision parse (OpenAI/fallback)
                                            └─ Risk engine validation
                                                 ├─ APPROVED  ──▶ write MT5 bridge command
                                                 ├─ REJECTED  ──▶ log reason, skip
                                                 └─ REVIEW    ──▶ log for manual check
```

> **API call optimisation**: The pipeline now runs a quick heuristic preview
> *before* calling the intent-classification API. If the message is
> text-only and the heuristic can already parse a complete signal (side +
> at least one of entry / SL / TP), the intent call is skipped entirely
> and the message goes straight to execution. This significantly reduces
> per-message API usage during high-volume periods.
>
> Additionally, the `parse_signal` AI call now returns an `intent` field
> alongside the trade data, so future flows can consolidate intent +
> extraction into a single AI round-trip.

### MT5 Bridge file format

```
request_id=abc-123
submitted_epoch=1779111958
symbol=XAUUSDm
action=BUY
order_type=MARKET
volume=0.01
stop_loss=4513.74
take_profit=4596.05
comment=TG|ALGO-TRADING-FOR|79112238
```

The EA returns a `.result` file:
```
request_id=abc-123
status=FILLED
message=done at 4572.290
ticket=12345678
executed_price=4572.290
executed_at=2026.05.19 13:45:59
```

---

## Supported Signal Formats

The heuristic parser handles all of these without AI:

```
# Standard text signal
GOLD BUY NEAR 4569/4566
SL 4562
TP 4574
TP 4580
TP 4599

# Slash-style labels
XAUUSD SELL NOW: 4582 4586
S/L: 4600
T/P1: 4580 T/P2: 4575 T/P3: 4556

# Unicode superscript TP labels (Trader Tactics / some CIS channels)
XAUUSD BUY 4505
Tp¹ 4508  Tp² 4512  Tp³ 4516
SL 4495

# ALGO TRADING forex. — "New" / "Both New" captions with MT5 position card image
# The image OCR is parsed as a trade signal (not a P&L update)
Caption: "New"
Image shows: XAUUSD, sell 0.50 ... S/L: 4575.16 ... T/P: 4491.53

# Inline entry
BUY GOLD NOW @ 2320 SL 2315 TP1 2330 TP2 2338
```

Symbol aliases recognised: `GOLD → XAUUSD`, `XAU → XAUUSD`, `EU → EURUSD`, `GU → GBPUSD`, `UJ → USDJPY`, `DOW/DJ30 → US30`, `NASDAQ/NDX/NQ → NAS100`

---

## Troubleshooting

### EA not picking up commands
- Confirm AutoTrading is ON (green toolbar button)
- Check EA chart comment shows `CONNECTED`
- Check MT5 Experts log: `MQL5\Logs\YYYYMMDD.log`
- Verify `BridgeFolderName` in EA settings matches `MT5_BRIDGE_DIR` in `.env`

### "Invalid stops" errors
- The broker's minimum stop distance is larger than the SL in the signal
- This is a broker rule — not a code issue. Try a broker with tighter spreads or wait for clearer signals

### "Command volume must be greater than zero"
- Means the EA compiled binary is outdated. Recompile from `mt5/Experts/TelegramSignalCopierEA.mq5`
- Root cause: old binary used `FILE_ANSI` without `FILE_BIN` — fixed in current version

### AI vision circuit breaker tripped
- All AI providers have rate limits and exponential back-off
- Circuit breaker resets automatically (typically within 1 hour)
- While tripped, text signals still work; image-only signals use OCR fallback

### Trades closed early by another EA
- Another EA (e.g. `Williams_Fractal_Scalper`) may call `PositionClose()` on all positions
- The `MagicNumber` input (default `20260001`) tags positions — well-coded EAs will skip them
- For EAs that ignore magic numbers: remove them from the same chart as `TelegramSignalCopierEA`

### Telegram OTP / session expired
- Delete the `.session` file in `runtime/sessions/` and restart to re-authenticate

### `Failed to load SSL library` on Windows startup
- Symptom in logs: `Failed to load SSL library: <class 'OSError'> (no library called "ssl" found)`
- Current builds auto-apply a Windows OpenSSL compatibility shim before Telethon import.
- If warning still appears on a target machine, install OpenSSL runtime:

```powershell
winget install --id ShiningLight.OpenSSL.Light --exact --accept-package-agreements --accept-source-agreements --silent
```

- Then restart listener.
- If `winget` is unavailable, install manually from slproweb OpenSSL Win64 package and restart.

---

## Key Files Reference

| File | Purpose |
|---|---|
| `mt5/Experts/TelegramSignalCopierEA.mq5` | MT5 Expert Advisor source (compile this in MetaEditor) |
| `src/telegram_signal_copier/main.py` | Listener entry point |
| `src/telegram_signal_copier/config.py` | All `.env` variable definitions and defaults |
| `src/telegram_signal_copier/services/pipeline.py` | Full signal processing pipeline |
| `src/telegram_signal_copier/services/signal_parser.py` | Heuristic + AI parser, MT5 screenshot format handler |
| `src/telegram_signal_copier/services/risk_engine.py` | Trade validation rules |
| `src/telegram_signal_copier/adapters/bridge.py` | Writes commands / reads results from MT5 bridge files |
| `src/telegram_signal_copier/models/contracts.py` | `TradeCommand` and `ExecutionResult` data models |
| `logs/telegram_signal_copier.log` | Full pipeline log (every signal, decision, execution) |
| `tools/supervisor.py` | Auto-restart daemon for the listener |

---

## Overview

## Core Goal

Build a copier that can:

1. Connect to Telegram.
2. Monitor many groups or channels at the same time.
3. Read trading signals from plain text, forwarded messages, and images.
4. Use AI to convert raw messages into structured trade instructions.
5. Apply validation and risk rules before execution.
6. Connect to MT5 through MCP and place trades automatically.
7. Track status, errors, and trade history.

## Main Features

### 1. Telegram Integration

- Connect with a Telegram user session or bot where allowed.
- Join and monitor multiple groups, supergroups, and channels.
- Store source metadata such as group name, message ID, sender, timestamp, and original content.
- Support real-time message streaming.

### 2. Signal Intake

- Accept signal messages in:
  - Plain text
  - Captions
  - Forwarded messages
  - Images and screenshots
- Preserve original message payload for audit and reprocessing.
- Detect message edits and updates when possible.

### 3. AI Signal Analysis

- Use AI to extract structured signal fields from raw content.
- Support signal fields such as:
  - Symbol
  - Side (`BUY` or `SELL`)
  - Entry price or entry zone
  - Stop loss
  - Take profit targets
  - Risk note
  - Market order vs pending order
  - Confidence score
- Handle inconsistent writing styles across different Telegram groups.
- Use OCR and image understanding for screenshots containing signal text.
- Return normalized JSON output for downstream execution.

### 4. Validation Layer

- Reject incomplete or low-confidence signals.
- Detect duplicate or repeated signals.
- Enforce configurable rules:
  - Allowed symbols
  - Max risk per trade
  - Max open trades
  - Allowed lot size range
  - Allowed trading hours
  - Minimum AI confidence
- Require human approval for uncertain signals if desired.

### 5. MT5 Trade Execution via EA Bridge

- Connect to MT5 through a local bridge that the MT5 Expert Advisor can read from the terminal common files directory.
- Keep Python-side AI logic outside MT5 and terminal-side order execution inside MT5.
- Leave room for adding an MCP server wrapper later if you want remote tool-based control.
- Support actions:
  - Open market orders
  - Place pending orders
  - Modify stop loss or take profit
  - Close trades
  - Partially close trades
- Map parsed signal data into MT5 order parameters.
- Capture execution response, ticket number, rejection reason, and fill price.

### 6. Monitoring and Audit

- Log every step of the pipeline:
  - Message received
  - AI parsed output
  - Validation decision
  - Order request
  - MT5 response
- Keep an audit trail for manual review.
- Provide a dashboard or admin panel later for status and trade history.

## Suggested System Architecture

```text
Telegram Groups/Channels
        |
        v
Telegram Listener Service
        |
        v
Message Queue / Event Bus
        |
        +--> Image OCR / Vision Service
        |
        v
AI Signal Parser
        |
        v
Validation + Risk Engine
        |
        v
Shared Bridge Files
  |
  v
MT5 Expert Advisor
        |
        v
MetaTrader 5

Side services:
- Config store
- Trade database
- Logs and alerts
```

## Recommended Modules

### `telegram_listener`

- Authenticates with Telegram.
- Subscribes to configured groups/channels.
- Pushes incoming messages into processing pipeline.

### `signal_parser`

- Accepts raw text or OCR result.
- Calls AI model with prompt templates.
- Returns structured JSON.

### `image_processor`

- Extracts text from screenshots.
- Optionally uses multimodal AI for chart or signal card interpretation.

### `risk_engine`

- Applies business rules.
- Decides approve, reject, or manual review.

### `mt5_executor`

- Writes approved trade commands into the MT5 bridge inbox.
- Reads execution results produced by the MT5 Expert Advisor.

### `mt5_ea`

- Runs inside MetaTrader 5.
- Polls shared bridge files.
- Validates symbol and order type.
- Places trade and writes result back.

### `storage`

- Stores groups, messages, parsed signals, trade decisions, and execution logs.

### `api_or_dashboard`

- Lets you manage groups, API keys, rules, and monitoring.

## Example AI Output Schema

```json
{
  "source_group": "Gold Signals VIP",
  "message_id": "12345",
  "signal_type": "market_order",
  "symbol": "XAUUSD",
  "side": "BUY",
  "entry": {
    "type": "market",
    "price": null,
    "range": null
  },
  "stop_loss": 2315.0,
  "take_profits": [2330.0, 2338.0],
  "confidence": 0.92,
  "raw_text": "BUY GOLD NOW SL 2315 TP 2330 2338",
  "image_used": false,
  "requires_review": false
}
```

## Example Processing Flow

1. New Telegram message arrives from a watched group.
2. System detects whether content is text, image, or both.
3. If image exists, OCR or multimodal extraction runs first.
4. AI parser converts content to structured trade data.
5. Validation layer checks confidence, duplicates, and risk limits.
6. Approved signal is sent to MT5 through MCP.
7. Execution result is stored and logged.

## Current Implementation

This repo now includes:

- Python service scaffold for Telegram intake, AI parsing, image handling, validation, and bridge submission.
- MQL5 Expert Advisor that polls command files and executes market or pending orders.
- Shared file contract between Python and MT5 using the MT5 common files directory.
- Sample CLI mode for local signal testing before live Telegram hookup.
- Telegram MCP server for VS Code or other MCP hosts using the same signed-in Telegram account session.

## Tech Stack Suggestion

- Backend: Python or Node.js
- Telegram client: Telethon or Pyrogram for Python
- AI parsing: OpenAI or another LLM API with structured output
- OCR: Tesseract, PaddleOCR, or cloud OCR
- Database: PostgreSQL
- Queue: Redis or RabbitMQ
- MT5 integration: Expert Advisor bridge now, optional MCP wrapper later
- Admin UI: FastAPI + simple frontend, or Next.js dashboard

## Configuration Needed

You said API keys will be available. Minimum configuration should include:

- Telegram credentials
- AI provider API key
  - Optionally configure multiple providers and fallbacks using the `.env` keys documented below.
- OCR provider key if external OCR is used
- MCP server connection settings for MT5
- MT5 account or terminal connection details
- Risk settings per account
- List of allowed Telegram groups/channels

## Important Safety Controls

- Do not place trades when parsed fields are missing.
- Do not trade if symbol mapping is uncertain.
- Add per-group enable/disable toggle.
- Add dry-run mode before live execution.
- Add rate limiting and duplicate suppression.
- Add manual approval mode for early testing.
- Encrypt stored credentials.

## MVP Scope

Phase 1 should focus on:

1. Connect to Telegram.
2. Watch selected groups.
3. Parse text signals with AI.
4. Support image OCR for simple screenshots.
5. Validate signals.
6. Send approved orders to MT5 via MCP.
7. Store logs and trade results.

## Future Enhancements

- Multi-account MT5 execution
- Per-group prompt tuning
- Confidence calibration by source group
- Performance analytics by signal provider
- Auto-close and trade management rules
- Web dashboard for approvals and monitoring
- Backtesting on historical Telegram messages

## Quick Start

1. Copy `.env.example` to `.env` and fill in Telegram and AI keys.
2. Install project in a Python 3.11+ environment.
3. Run Telegram login once to create a local session file.
4. Attach `mt5/Experts/TelegramSignalCopierEA.mq5` to an MT5 chart.
5. Make sure the EA bridge folder name matches the Python bridge path.
6. Run a local sample signal first.
7. Turn off `DRY_RUN` only after bridge flow is confirmed.

### Telegram Login

```powershell
python -m telegram_signal_copier login
```

## AI Providers and OCR Setup

- Supported AI providers: OpenAI-compatible primary provider plus optional fallbacks (Cloudflare, NVIDIA, Cerebras).
- Configure provider keys and base URLs in `.env` (see `.env.example`).
- Important: fallbacks must be real OpenAI-compatible endpoints or use the provider-specific adapter settings; invalid endpoints will fail and be skipped.

Local OCR (recommended as fallback):

- Install system Tesseract engine (OS packages):
  - Windows: install Tesseract and ensure `tesseract.exe` on PATH
  - Linux: `sudo apt install tesseract-ocr`
- Python packages: `pillow` and `pytesseract` (added to `requirements.txt`).

AI tuning variables (in `.env`):

- `AI_MAX_REQUESTS_PER_MINUTE`: Global token-bucket cap to protect provider quota.
- `AI_PROVIDER_COOLDOWN_SECONDS`: Base cooldown applied on a provider failure.
- `AI_PROVIDER_MAX_COOLDOWN_SECONDS`: Maximum cooldown when failures escalate.
- `AI_CACHE_TTL_SECONDS`: Time in seconds to cache identical prompt+image responses.

If you plan to use local OCR as a fallback, ensure `pytesseract` and the Tesseract binary are installed before running the service.


This will prompt for the Telegram OTP on first sign-in and save the session locally.

## Telegram MCP in VS Code

This workspace now includes [.vscode/mcp.json](.vscode/mcp.json), which starts a local MCP server exposing Telegram tools through the signed-in Telethon session.

Available MCP tools:

- `telegram_connection_status`
- `telegram_list_dialogs`
- `telegram_get_recent_messages`
- `telegram_send_message`

Important limitation:

- This does not control the Telegram Desktop app process directly.
- It connects to the same Telegram account through the Telegram API and local session, which is the practical way to expose Telegram through MCP.

After you trust and start the MCP server in VS Code, you can ask chat to inspect dialogs and messages through those tools.

### Sample Local Run

```powershell
python -m telegram_signal_copier sample --text "BUY GOLD NOW SL 2315 TP 2330 TP 2338"
```

## Build Plan

1. Create Telegram listener.
2. Define normalized signal schema.
3. Build AI prompt and parser pipeline.
4. Add OCR for image signals.
5. Build validation and risk engine.
6. Integrate MT5 execution bridge and EA.
7. Add logging, storage, and manual review tools.

## Deliverable Summary

This project should act as an AI-powered Telegram signal copier that listens to many trading groups, understands text and image signals, validates them, and executes trades on MT5 through MCP with strong logging and risk controls.