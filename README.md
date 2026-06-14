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
7. [EA Floating Profit Close-All](#ea-floating-profit-close-all)
8. [Running the Listener](#running-the-listener)
9. [How Signals Are Processed](#how-signals-are-processed)
10. [Supported Signal Formats](#supported-signal-formats)
11. [Troubleshooting](#troubleshooting)
12. [Key Files Reference](#key-files-reference)

---

## Architecture Overview

```text
Telegram Groups / Channels
        │
        ▼
  TelegramSignalListener (Telethon)
        │  raw messages + images
        ▼
  MessageClusterAgent            ← buffers & groups related messages (cluster_agent.py)
        │
        ▼
  Signal Pipeline (pipeline.py)
  ├── Stage 1: Intent filter     ← heuristic preview → skips AI call for complete text signals
  │            (pipeline_intent.py + intent_classifier.py)
  ├── Stage 2: Heuristic parse   ← fast regex extraction (signal_heuristic_parse.py)
  ├── Stage 3: OCR (Tesseract)   ← extracts text from chart images (image_processor.py)
  ├── Stage 4: AI vision parse   ← OpenAI / Cloudflare / Groq (openai_client.py)
  └── Stage 5: Risk engine       ← validates SL/TP/confidence/symbol (risk_engine.py)
        │
        ▼
  MT5 File Bridge (bridge.py)
  ├── bridge_root/               ← command files written here
  │   ├── <request_id>.txt       ← key=value trade command
  │   ├── command_queue.txt      ← EA reads this list
  │   └── outbox/<id>.result     ← EA writes result here
        │
        ▼
  TelegramSignalCopierEA (MT5)   ← polls bridge, places orders, writes result
```

### Module structure (post-refactor)

All source files are kept under **300 lines** for maintainability. Large originals were split:

| Split | Result modules |
|---|---|
| `main.py` (532→208 lines) | + `listener_builder`, `listener_runner`, `listener_lock`, `listener_status` |
| `signal_parser.py` (888→134 lines) | + `signal_patterns`, `signal_normalizers`, `signal_heuristic`, `signal_heuristic_parse`, `signal_ai_merge`, `signal_crypto` |
| `developer_agent.py` (754→48 lines) | + `developer_agent_models`, `developer_agent_analysis`, `developer_agent_patch`, `developer_agent_fp` |
| `openai_client.py` (453→300 lines) | + `openai_prompts`, `openai_utils` |
| `cluster_agent.py` (359→159 lines) | + `cluster_parser` |
| `config.py` (408→262 lines) | + `config_helpers` |
| `telegram_client.py` (382→268 lines) | + `telegram_helpers` |
| `bridge.py` (379→281 lines) | + `bridge_helpers` |
| `pipeline.py` (349→296 lines) | + `pipeline_intent` |
| `graph.py` (335→213 lines) | + `graph_listener` |

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

## EA Floating Profit Close-All

The EA includes an optional risk-control feature that closes all matching open positions when total floating profit reaches a configured USD threshold.

### Inputs

| Parameter | Default | Description |
|---|---:|---|
| `EnableFloatingProfitCloseAll` | `false` | Enable/disable the floating-profit close-all safety feature |
| `FloatingProfitCloseAllUsd` | `100.0` | Profit threshold in account currency, e.g. `100` USD |
| `FloatingProfitCloseAllOnlyManagedMagic` | `true` | Only close positions opened by this EA (`MagicNumber`) |
| `FloatingProfitCloseAllCooldownSeconds` | `60` | Minimum cooldown between close-all triggers |

### Recommended settings

For automatic close-all at `$100` floating profit, set:

```text
EnableFloatingProfitCloseAll = true
FloatingProfitCloseAllUsd = 100.0
FloatingProfitCloseAllOnlyManagedMagic = true
FloatingProfitCloseAllCooldownSeconds = 60
```

The EA calculates:

```text
total floating profit = POSITION_PROFIT + POSITION_SWAP
```

When the total reaches the threshold, it closes matching open positions and writes the event to the MT5 journal.

### Important

This feature runs inside the MT5 EA only. It does **not** require Python listener changes, bridge command changes, or a new Python EXE build.

After changing the EA source, recompile the EA in MetaEditor and attach/restart it on the chart.

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

### Floating profit close-all not triggering
- Check EA inputs: `EnableFloatingProfitCloseAll` must be `true`
- Confirm `FloatingProfitCloseAllOnlyManagedMagic` matches your positions:
  - `true` closes only EA-managed positions with `MagicNumber=20260001`
  - `false` closes all open positions on the account
- Check MT5 Experts log for:
  - `TelegramSignalCopierEA floating profit close-all triggered`
  - `TelegramSignalCopierEA floating profit close-all completed`
- Recompile the EA after changing `mt5/Experts/TelegramSignalCopierEA.mq5`

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

### Entry point & configuration

| File | Purpose |
|---|---|
| `mt5/Experts/TelegramSignalCopierEA.mq5` | MT5 Expert Advisor source; includes bridge execution, multi-target automation, and floating-profit close-all safety |
| `src/telegram_signal_copier/main.py` | Listener entry point — arg parsing, logging setup, health check |
| `src/telegram_signal_copier/config.py` | `AppConfig` dataclass, `.env` variable definitions and defaults |
| `src/telegram_signal_copier/config_helpers.py` | dotenv loading, AI provider builder, env-parsing helpers |
| `src/telegram_signal_copier/constants.py` | Shared constants (symbol aliases, regex fragments) |

### Listener subsystem (split from main.py)

| File | Purpose |
|---|---|
| `src/telegram_signal_copier/listener_builder.py` | `build_pipeline()` factory — wires up pipeline with config |
| `src/telegram_signal_copier/listener_runner.py` | Async runner: `_run_listener`, `_run_with_restarts`, heartbeat |
| `src/telegram_signal_copier/listener_lock.py` | Lock/PID file helpers — prevents duplicate listener processes |
| `src/telegram_signal_copier/listener_status.py` | Bridge status file writers (`telegram_status.txt`, source map) |

### Signal pipeline

| File | Purpose |
|---|---|
| `src/telegram_signal_copier/services/pipeline.py` | `CopierPipeline` — orchestrates all stages end-to-end |
| `src/telegram_signal_copier/services/pipeline_intent.py` | Stage 1 intent classification (heuristic preview + AI) |
| `src/telegram_signal_copier/services/pipeline_logger.py` | JSONL pipeline event logger |
| `src/telegram_signal_copier/services/risk_engine.py` | Trade validation: SL/TP sanity, RR ratio, confidence gate |
| `src/telegram_signal_copier/services/deduplication.py` | Deduplication cache to suppress repeated signals |

### Signal parsing (split from signal_parser.py)

| File | Purpose |
|---|---|
| `src/telegram_signal_copier/services/signal_parser.py` | Thin coordinator: `SignalParser.parse()`, delegates to submodules |
| `src/telegram_signal_copier/services/signal_patterns.py` | All regex patterns and compiled constants |
| `src/telegram_signal_copier/services/signal_normalizers.py` | Symbol/side/price normalizers, `detect_order_type` |
| `src/telegram_signal_copier/services/signal_heuristic.py` | Cluster-context parser, MT5 screenshot parser |
| `src/telegram_signal_copier/services/signal_heuristic_parse.py` | Main `heuristic_parse()` function (entry range, SL/TP scan) |
| `src/telegram_signal_copier/services/signal_ai_merge.py` | AI payload builder, `merge_signals`, `fill_missing_levels_from_chart` |
| `src/telegram_signal_copier/services/signal_crypto.py` | Crypto-specific entry price recovery heuristics |

### Cluster / message buffering

| File | Purpose |
|---|---|
| `src/telegram_signal_copier/services/cluster_agent.py` | `MessageClusterAgent` — buffers related messages into clusters |
| `src/telegram_signal_copier/services/cluster_parser.py` | `parse_cluster()`, `ClusterSignal`, `auto_derive_sl()` |
| `src/telegram_signal_copier/services/message_buffer.py` | Low-level message accumulation buffer |

### Adapters

| File | Purpose |
|---|---|
| `src/telegram_signal_copier/adapters/bridge.py` | `FileBridgeExecutor` — writes commands, reads results from MT5 |
| `src/telegram_signal_copier/adapters/bridge_helpers.py` | Static bridge utilities (payload builder, symbol retry logic) |
| `src/telegram_signal_copier/adapters/telegram_client.py` | `TelegramSignalListener` — Telethon connection, message dispatch |
| `src/telegram_signal_copier/adapters/telegram_helpers.py` | SSL shim, platform patch, `MessageBuffer`, source name normalizer |
| `src/telegram_signal_copier/adapters/openai_client.py` | `OpenAIClient` — provider fallback, rate limiting, circuit breaker |
| `src/telegram_signal_copier/adapters/openai_prompts.py` | System prompt strings for parse_signal / classify_intent / chart levels |
| `src/telegram_signal_copier/adapters/openai_utils.py` | `json_from_text`, `image_data_url`, `compute_cache_key`, `build_providers` |
| `src/telegram_signal_copier/adapters/ai_cache.py` | In-memory + optional persistent AI response cache |
| `src/telegram_signal_copier/adapters/circuit_breaker.py` | Circuit breaker for AI provider health management |
| `src/telegram_signal_copier/adapters/provider_adapters.py` | Per-provider HTTP adapter (OpenAI, Cloudflare, NVIDIA, Groq, etc.) |

### Agents

| File | Purpose |
|---|---|
| `src/telegram_signal_copier/agents/graph.py` | `_Pipeline`, `build_graph()`, `run_on_message()` — LangGraph-free pipeline |
| `src/telegram_signal_copier/agents/graph_listener.py` | `start_listener()` — legacy Telethon listener wired to agent graph |
| `src/telegram_signal_copier/agents/intent_filter.py` | Intent filter node |
| `src/telegram_signal_copier/agents/extraction_agent.py` | Signal extraction node |
| `src/telegram_signal_copier/agents/validation_agent.py` | Validation node |
| `src/telegram_signal_copier/agents/execution_agent.py` | Trade execution node |
| `src/telegram_signal_copier/agents/developer_agent.py` | Re-export shim for `classify_failures`, `apply_patch`, etc. |
| `src/telegram_signal_copier/agents/developer_agent_models.py` | `FailureReport`, `Patch`, `FalsePositiveReport` dataclasses |
| `src/telegram_signal_copier/agents/developer_agent_analysis.py` | `classify_failures()` — log analysis and failure categorisation |
| `src/telegram_signal_copier/agents/developer_agent_patch.py` | `generate_patch`, `apply_patch`, `rollback_last_patch` |
| `src/telegram_signal_copier/agents/developer_agent_fp.py` | `assess_false_positives`, `fix_false_positives` |

### Models & misc

| File | Purpose |
|---|---|
| `src/telegram_signal_copier/models/contracts.py` | `TradeCommand`, `ExecutionResult`, `TelegramSignalMessage` |
| `src/telegram_signal_copier/services/intent_classifier.py` | Standalone intent classifier used by pipeline_intent |
| `src/telegram_signal_copier/services/image_processor.py` | Tesseract OCR + AI vision image processing |
| `src/telegram_signal_copier/services/trade_tracker.py` | Open-position tracker, partial-close state |
| `src/telegram_signal_copier/services/message_logger.py` | Raw message JSONL logger |
| `src/telegram_signal_copier/services/telegram_session.py` | Telethon session management helpers |
| `src/telegram_signal_copier/mcp_server.py` | Optional MCP server endpoint |
| `logs/telegram_signal_copier.log` | Full pipeline log (every signal, decision, execution) |
| `tools/supervisor.py` | Auto-restart daemon for the listener |

---
