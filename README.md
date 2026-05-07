# Telegram Signal Copier

## Overview

Telegram Signal Copier is a trading automation system that connects to one Telegram account, listens to multiple signal groups or channels, uses AI to extract and validate trading signals from text and images, and sends approved trades to MetaTrader 5 through a Python service plus MT5 Expert Advisor bridge.

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