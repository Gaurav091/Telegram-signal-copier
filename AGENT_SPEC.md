# Telegram Signal Copier — Intelligent Agent Specification

**Version:** 2.0  
**Date:** 2026-05-08  
**Purpose:** Complete specification for GitHub Copilot / AI assistant to implement, debug, and extend the intelligent signal-copying pipeline.

---

## 1. Project Goal (Plain English)

Build a system that behaves like an **experienced human trader** monitoring a Telegram channel. A human trader would:

1. Read every message but **not act on every message**
2. Understand **context across multiple messages** (a chart image followed by a text confirmation is one trade, not two)
3. Recognize that some messages are **trade calls**, some are **updates** (TP hit, SL moved), and some are **just commentary**
4. Know that a **chart screenshot** showing a long arrow means "buy", even if the word "buy" never appears
5. Know that **"🎉 TP1 hit!"** means update an existing trade, not open a new one
6. **Never double-open** a trade it already acted on
7. Handle **partial closes, trailing stops, breakeven moves** from update messages

The system must do all of this automatically, across text messages, image messages, and mixed (text + image) messages, using multiple AI API keys for redundancy and throughput.

---

## 2. High-Level Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        Telegram Layer                           │
│  Telethon listener — receives messages from monitored channels  │
└───────────────────────────┬─────────────────────────────────────┘
                            │ raw Message objects (text / photo / album)
                            ▼
┌─────────────────────────────────────────────────────────────────┐
│                    Message Buffer & Grouper                     │
│  Groups messages by time window + sender + topic               │
│  Detects albums (multi-image posts)                            │
│  Holds messages N seconds before releasing to analyzer         │
└───────────────────────────┬─────────────────────────────────────┘
                            │ MessageGroup objects
                            ▼
┌─────────────────────────────────────────────────────────────────┐
│                   Context Window Manager                        │
│  Maintains rolling history of last K messages per channel      │
│  Attaches prior context to each new group for AI analysis      │
│  Tracks open trades and their states                           │
└───────────────────────────┬─────────────────────────────────────┘
                            │ AnalysisRequest (group + context)
                            ▼
┌─────────────────────────────────────────────────────────────────┐
│                    AI Analysis Orchestrator                     │
│  Routes to best available API key (round-robin + health check) │
│  Stage 1: Intent classifier  — what type of message is this?   │
│  Stage 2: Data extractor     — extract trade parameters        │
│  Stage 3: Confidence scorer  — is this actionable?             │
│  Stage 4: Action resolver    — new trade / modify / close /    │
│                                update only / ignore            │
└───────────────────────────┬─────────────────────────────────────┘
                            │ ResolvedAction objects
                            ▼
┌─────────────────────────────────────────────────────────────────┐
│                      Risk Engine                               │
│  Validates symbol, computes lot size, checks daily limits      │
│  Deduplication guard (prevents re-acting on same signal)       │
└───────────────────────────┬─────────────────────────────────────┘
                            │ validated TradeInstruction objects
                            ▼
┌─────────────────────────────────────────────────────────────────┐
│                    FileBridge Adapter                          │
│  Writes .cmd files consumed by MT5 EA                         │
│  Monitors .result files for confirmation                       │
└─────────────────────────────────────────────────────────────────┘
```

---

## 3. Message Classification System

### 3.1 Message Intent Categories

Every message (or grouped set of messages) must be classified into exactly one of these intents before any action is taken:

```python
class MessageIntent(str, Enum):
    NEW_TRADE_SIGNAL    = "new_trade_signal"     # Open a new position
    TRADE_UPDATE        = "trade_update"          # Modify existing position
    TP_HIT              = "tp_hit"                # Take profit level reached
    SL_HIT              = "sl_hit"                # Stop loss hit / trade closed
    BREAKEVEN_MOVE      = "breakeven_move"        # Move SL to entry
    PARTIAL_CLOSE       = "partial_close"         # Close part of position
    SL_MODIFICATION     = "sl_modification"       # Move SL to new level
    TP_MODIFICATION     = "tp_modification"       # Change TP level
    TRADE_CANCEL        = "trade_cancel"          # Cancel pending / close now
    MARKET_COMMENTARY   = "market_commentary"     # Analysis, no trade action
    PROVIDER_UPDATE     = "provider_update"       # Channel admin message
    AMBIGUOUS           = "ambiguous"             # Needs more context
    IRRELEVANT          = "irrelevant"            # Not trade-related at all
```

### 3.2 Image Sub-Types

Images must additionally be classified by visual content:

```python
class ImageType(str, Enum):
    CHART_WITH_ANNOTATION   = "chart_with_annotation"   
    # TradingView/MT4/MT5 chart with drawn arrows, boxes, lines
    # indicating entry zone, SL zone, TP zone
    
    ORDER_SCREENSHOT        = "order_screenshot"         
    # MT4/MT5/broker platform screenshot showing an open or 
    # pending order with SL/TP fields visible
    
    RESULT_SCREENSHOT       = "result_screenshot"        
    # Closed trade screenshot showing profit/loss
    
    PROFIT_CELEBRATION      = "profit_celebration"       
    # Stylized image (e.g. green candle, trophy) celebrating a win
    
    SIGNAL_CARD             = "signal_card"              
    # Formatted signal image (common in signal channels):
    # symbol, direction, entry, SL, TP laid out as a card
    
    MARKET_CHART_ONLY       = "market_chart_only"        
    # Plain chart with no annotation — informational only
    
    UNKNOWN_IMAGE           = "unknown_image"
```

---

## 4. Message Grouping and Context Window

### 4.1 Why Grouping Is Required

A signal provider may send a trade in any of these patterns:

```
Pattern A — Single text message:
  [MSG 1] "EURUSD BUY 1.0850 SL 1.0800 TP1 1.0900 TP2 1.0950"

Pattern B — Chart image + text confirmation:
  [MSG 1] <image: chart with long arrow>
  [MSG 2] "Entry confirmed, buy now"          ← arrives 10-30 seconds later

Pattern C — Signal card image only:
  [MSG 1] <image: formatted signal card with all parameters>

Pattern D — Text setup + order screenshot:
  [MSG 1] "Taking this setup on GBPUSD"
  [MSG 2] <image: MT5 order ticket showing SL/TP>

Pattern E — Multi-message build-up:
  [MSG 1] "Watching XAUUSD closely"
  [MSG 2] "Looks like it's going to break"
  [MSG 3] <chart image>
  [MSG 4] "BUY at 2320, SL 2300, TP 2380"    ← THIS is the actual signal

Pattern F — Update message:
  [MSG 1] "🎉 TP1 hit on EURUSD, move SL to breakeven"
```

The grouper must handle all patterns without human intervention.

### 4.2 MessageBuffer Implementation

```python
# src/telegram_signal_copier/services/message_buffer.py

import asyncio
import time
from dataclasses import dataclass, field
from typing import List, Optional
from collections import defaultdict

@dataclass
class RawMessage:
    """Wrapper around a Telethon message with extracted metadata."""
    msg_id: int
    channel_id: int
    sender_id: Optional[int]
    timestamp: float                    # Unix time
    text: Optional[str]                 # Message text or caption
    has_image: bool
    image_bytes: Optional[bytes]        # Downloaded image bytes if present
    grouped_id: Optional[int]           # Telegram album grouping ID
    reply_to_msg_id: Optional[int]      # If this is a reply

@dataclass
class MessageGroup:
    """
    A collection of 1+ raw messages that together form one logical signal.
    Populated by the MessageBuffer and released to the analyzer.
    """
    group_id: str                       # Unique ID for this group
    channel_id: int
    messages: List[RawMessage] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    released: bool = False

    @property
    def combined_text(self) -> str:
        """All text from all messages joined for AI analysis."""
        parts = [m.text for m in self.messages if m.text]
        return "\n".join(parts)

    @property
    def all_images(self) -> List[bytes]:
        """All images from all messages in order."""
        return [m.image_bytes for m in self.messages if m.image_bytes]

class MessageBuffer:
    """
    Collects incoming messages and groups them into logical signal units.
    
    Grouping rules (in priority order):
    1. Telegram album ID — messages with same grouped_id are always together
    2. Reply chain — a message replying to a recent message joins its group
    3. Time window — messages from same channel within WINDOW_SECONDS of 
       each other are candidates for grouping
    4. Content coherence — AI micro-classifier confirms they are related
       (checked only when time window rule fires)
    
    A group is "released" (sent for analysis) when:
    - RELEASE_AFTER_SECONDS have passed since the last message in the group
    - OR a message arrives that clearly starts a NEW unrelated topic
    """

    WINDOW_SECONDS = 45         # Messages within 45s of each other may group
    RELEASE_AFTER_SECONDS = 30  # Release group 30s after last message
    MAX_GROUP_SIZE = 8          # Never group more than 8 messages together
    CONTEXT_HISTORY_SIZE = 20   # Keep last 20 released groups per channel

    def __init__(self, release_callback):
        """
        release_callback: async callable that receives a MessageGroup
        """
        self._pending: dict[int, list[MessageGroup]] = defaultdict(list)
        self._history: dict[int, list[MessageGroup]] = defaultdict(list)
        self._release_callback = release_callback
        self._lock = asyncio.Lock()

    async def ingest(self, message: RawMessage) -> None:
        async with self._lock:
            group = self._find_or_create_group(message)
            group.messages.append(message)
        
    async def tick(self) -> None:
        """Call this every second from an asyncio task to release ready groups."""
        now = time.time()
        async with self._lock:
            for channel_id, groups in self._pending.items():
                ready = [
                    g for g in groups 
                    if not g.released and 
                    (now - max(m.timestamp for m in g.messages)) 
                    >= self.RELEASE_AFTER_SECONDS
                ]
                for group in ready:
                    group.released = True
                    self._history[channel_id].append(group)
                    # Trim history
                    if len(self._history[channel_id]) > self.CONTEXT_HISTORY_SIZE:
                        self._history[channel_id].pop(0)
                    await self._release_callback(group)
            
            # Clean up released groups from pending
            for channel_id in self._pending:
                self._pending[channel_id] = [
                    g for g in self._pending[channel_id] if not g.released
                ]

    def get_context_history(self, channel_id: int) -> List[MessageGroup]:
        """Returns recent released groups for context injection."""
        return self._history.get(channel_id, [])

    def _find_or_create_group(self, msg: RawMessage) -> MessageGroup:
        channel_groups = self._pending[msg.channel_id]
        
        # Rule 1: Telegram album grouping
        if msg.grouped_id:
            for g in channel_groups:
                if any(m.grouped_id == msg.grouped_id for m in g.messages):
                    return g
        
        # Rule 2: Reply chain
        if msg.reply_to_msg_id:
            for g in channel_groups:
                if any(m.msg_id == msg.reply_to_msg_id for m in g.messages):
                    if len(g.messages) < self.MAX_GROUP_SIZE:
                        return g
        
        # Rule 3: Time window (most recent eligible group)
        now = msg.timestamp
        for g in reversed(channel_groups):
            if g.released:
                continue
            last_ts = max(m.timestamp for m in g.messages)
            if (now - last_ts) <= self.WINDOW_SECONDS:
                if len(g.messages) < self.MAX_GROUP_SIZE:
                    return g
        
        # Create new group
        import uuid
        new_group = MessageGroup(
            group_id=str(uuid.uuid4()),
            channel_id=msg.channel_id
        )
        channel_groups.append(new_group)
        return new_group
```

---

## 5. Multi-API Key Orchestrator

### 5.1 API Key Pool Configuration

```python
# src/telegram_signal_copier/adapters/ai_pool.py

from dataclasses import dataclass, field
from typing import List, Optional
from enum import Enum
import time
import asyncio
import logging

logger = logging.getLogger(__name__)

class APIProvider(str, Enum):
    OPENAI          = "openai"
    ANTHROPIC       = "anthropic"
    GOOGLE_GEMINI   = "google_gemini"
    OPENROUTER      = "openrouter"

@dataclass
class APIKeyConfig:
    """Configuration for a single API key."""
    key_id: str                         # Human label e.g. "openai_key_1"
    provider: APIProvider
    api_key: str
    model: str                          # e.g. "gpt-4o", "claude-3-5-sonnet"
    supports_vision: bool               # Can analyze images
    rpm_limit: int                      # Requests per minute
    tpm_limit: int                      # Tokens per minute (0 = unlimited)
    priority: int = 1                   # Lower = higher priority
    
    # Runtime state
    _request_timestamps: list = field(default_factory=list, repr=False)
    _consecutive_errors: int = field(default=0, repr=False)
    _circuit_open_until: float = field(default=0.0, repr=False)

    def is_healthy(self) -> bool:
        return time.time() >= self._circuit_open_until

    def is_rate_limited(self) -> bool:
        now = time.time()
        self._request_timestamps = [
            t for t in self._request_timestamps if now - t < 60
        ]
        return len(self._request_timestamps) >= self.rpm_limit

    def record_request(self):
        self._request_timestamps.append(time.time())

    def record_error(self, open_circuit_seconds: int = 60):
        self._consecutive_errors += 1
        if self._consecutive_errors >= 3:
            self._circuit_open_until = time.time() + open_circuit_seconds
            logger.warning(
                f"Circuit opened for {self.key_id} "
                f"for {open_circuit_seconds}s"
            )

    def record_success(self):
        self._consecutive_errors = 0


class AIKeyPool:
    """
    Manages multiple API keys across multiple providers.
    
    Selection strategy:
    1. Filter to keys that support required capability (vision or text)
    2. Filter to healthy keys (circuit not open)
    3. Filter to non-rate-limited keys
    4. Sort by priority then by fewest recent requests
    5. Return best key
    
    Falls back through providers automatically.
    """

    def __init__(self, configs: List[APIKeyConfig]):
        self.configs = configs

    def get_best_key(
        self, 
        needs_vision: bool = False,
        preferred_provider: Optional[APIProvider] = None
    ) -> Optional[APIKeyConfig]:
        
        candidates = [c for c in self.configs if c.is_healthy()]
        candidates = [c for c in candidates if not c.is_rate_limited()]
        
        if needs_vision:
            candidates = [c for c in candidates if c.supports_vision]
        
        if preferred_provider:
            preferred = [
                c for c in candidates 
                if c.provider == preferred_provider
            ]
            if preferred:
                candidates = preferred
        
        if not candidates:
            # Last resort: ignore rate limit, just check circuit
            candidates = [
                c for c in self.configs 
                if c.is_healthy() and 
                (not needs_vision or c.supports_vision)
            ]
        
        if not candidates:
            return None
        
        return sorted(
            candidates, 
            key=lambda c: (c.priority, len(c._request_timestamps))
        )[0]

    def get_all_healthy_vision_keys(self) -> List[APIKeyConfig]:
        """For consensus mode: get all healthy vision-capable keys."""
        return [
            c for c in self.configs 
            if c.is_healthy() and c.supports_vision
        ]
```

### 5.2 Environment Configuration for Multiple Keys

```ini
# .env — configure as many keys as needed

# === OpenAI Keys ===
OPENAI_API_KEY_1=sk-...
OPENAI_MODEL_1=gpt-4o
OPENAI_RPM_1=60

OPENAI_API_KEY_2=sk-...
OPENAI_MODEL_2=gpt-4o-mini
OPENAI_RPM_2=500

# === Anthropic Keys ===
ANTHROPIC_API_KEY_1=sk-ant-...
ANTHROPIC_MODEL_1=claude-3-5-sonnet-20241022
ANTHROPIC_RPM_1=50

# === Google Gemini Keys ===
GEMINI_API_KEY_1=AIza...
GEMINI_MODEL_1=gemini-1.5-pro
GEMINI_RPM_1=60

GEMINI_API_KEY_2=AIza...
GEMINI_MODEL_2=gemini-1.5-flash
GEMINI_RPM_2=1000

# === OpenRouter (access to many models via one key) ===
OPENROUTER_API_KEY_1=sk-or-...
OPENROUTER_MODEL_1=anthropic/claude-3.5-sonnet
OPENROUTER_RPM_1=200

# === Behavior ===
AI_CONSENSUS_MODE=false         # true = use 2 keys and compare results
AI_MIN_CONFIDENCE=0.75          # 0-1, below this threshold = do not trade
AI_CONTEXT_WINDOW_MESSAGES=15   # how many prior messages to include as context
MESSAGE_GROUP_WINDOW_SECONDS=45  
MESSAGE_GROUP_RELEASE_SECONDS=30
```

### 5.3 Loading API Keys from Environment

```python
# src/telegram_signal_copier/config.py  (addition)

import os
from adapters.ai_pool import APIKeyConfig, APIProvider, AIKeyPool

def load_ai_key_pool() -> AIKeyPool:
    """
    Reads all configured API keys from environment and builds the pool.
    Supports an arbitrary number of keys per provider by scanning
    sequentially numbered env vars.
    """
    configs = []
    
    provider_specs = [
        # (env_prefix, provider, supports_vision_default)
        ("OPENAI",      APIProvider.OPENAI,        True),
        ("ANTHROPIC",   APIProvider.ANTHROPIC,     True),
        ("GEMINI",      APIProvider.GOOGLE_GEMINI, True),
        ("OPENROUTER",  APIProvider.OPENROUTER,    True),
    ]
    
    for prefix, provider, vision in provider_specs:
        for i in range(1, 20):   # scan up to 19 keys per provider
            key = os.getenv(f"{prefix}_API_KEY_{i}")
            if not key:
                break
            model   = os.getenv(f"{prefix}_MODEL_{i}", _default_model(provider))
            rpm     = int(os.getenv(f"{prefix}_RPM_{i}", "60"))
            tpm     = int(os.getenv(f"{prefix}_TPM_{i}", "0"))
            priority= int(os.getenv(f"{prefix}_PRIORITY_{i}", "1"))
            
            configs.append(APIKeyConfig(
                key_id=f"{prefix.lower()}_key_{i}",
                provider=provider,
                api_key=key,
                model=model,
                supports_vision=vision,
                rpm_limit=rpm,
                tpm_limit=tpm,
                priority=priority,
            ))
    
    if not configs:
        raise RuntimeError(
            "No API keys configured. Set at least OPENAI_API_KEY_1 "
            "(or ANTHROPIC/GEMINI/OPENROUTER equivalent) in .env"
        )
    
    return AIKeyPool(configs)

def _default_model(provider: APIProvider) -> str:
    return {
        APIProvider.OPENAI:         "gpt-4o",
        APIProvider.ANTHROPIC:      "claude-3-5-sonnet-20241022",
        APIProvider.GOOGLE_GEMINI:  "gemini-1.5-pro",
        APIProvider.OPENROUTER:     "openai/gpt-4o",
    }[provider]
```

---

## 6. AI Analysis Pipeline — Four Stages

Every MessageGroup passes through four sequential AI analysis stages. Each stage uses the cheapest/fastest capable model available; only escalate to expensive models when needed.

### 6.1 Stage 1 — Intent Classification

**Goal:** Determine `MessageIntent` before doing expensive extraction.  
**Model preference:** Fast/cheap (GPT-4o-mini, Gemini Flash)  
**Input:** Combined text + image thumbnails (low-res)  
**Output:** `MessageIntent` + confidence float

```python
INTENT_CLASSIFICATION_PROMPT = """
You are an expert forex/crypto/commodity trading signal analyst.
You monitor a Telegram signal channel on behalf of a trader.

Your task: Classify the intent of the following message(s).

## Prior context (last {context_count} message groups from this channel):
{prior_context}

## Current message(s) to classify:
{current_messages}

## Images attached: {image_count} image(s)
{image_descriptions}

## Classification options:
- new_trade_signal     : A new trade is being called. Contains entry, or 
                         direction + symbol at minimum
- trade_update         : Updating an existing trade (SL move, partial close, 
                         breakeven, additional TP)
- tp_hit               : Notification that a take-profit level was reached
- sl_hit               : Notification that stop-loss was hit / trade closed
- breakeven_move       : Instruction to move SL to entry price
- partial_close        : Close part (e.g. 50%) of an existing position
- sl_modification      : Move SL to a specific new price level
- tp_modification      : Change TP to a new price level  
- trade_cancel         : Cancel a pending order or close immediately
- market_commentary    : Analysis or opinion, no trade action required
- provider_update      : Channel admin/housekeeping message
- ambiguous            : Cannot determine intent with confidence
- irrelevant           : Not related to trading at all

## Rules:
1. Celebration messages ("TP hit 🎉", "Profit secured ✅") = tp_hit or sl_hit
2. If message references "the previous signal" or "last trade" = trade_update
3. "Move SL to entry" or "breakeven" = breakeven_move
4. If you see ONLY a chart image with no text and no annotation arrows = 
   market_commentary (not a trade signal)
5. If chart has annotations (arrows, boxes, price labels) = likely new_trade_signal
6. An order screenshot (MT4/MT5 terminal) showing an already-open order = 
   trade_update or result_screenshot, not a new signal
7. If genuinely ambiguous, return ambiguous — do NOT guess

## Response format (JSON only, no other text):
{
  "intent": "<one of the options above>",
  "confidence": <0.0 to 1.0>,
  "reasoning": "<one sentence explaining why>",
  "referenced_symbol": "<symbol if detectable, else null>",
  "is_update_to_recent": <true if this updates a recently seen signal, false otherwise>
}
"""
```

### 6.2 Stage 2 — Trade Parameter Extraction

**Triggered only if** Stage 1 returns `new_trade_signal` with confidence ≥ 0.6  
**Model preference:** Full vision model (GPT-4o, Claude 3.5, Gemini 1.5 Pro)  
**Input:** Full text + full-resolution images  
**Output:** Structured `TradeParameters`

```python
EXTRACTION_PROMPT = """
You are an expert trade signal parser. Extract all trade parameters from the
message(s) and image(s) below.

## Prior context:
{prior_context}

## Message text:
{message_text}

## Image analysis instructions:
For each image, determine:
- If it is a CHART with annotations:
  * What is the symbol (look at chart title, axis labels, watermark)
  * What direction do the arrows/annotations indicate? (up arrow = BUY/LONG,
    down arrow = SELL/SHORT)
  * Are there horizontal lines labeled with prices? These are likely SL/TP
  * Is there a shaded zone? This is likely an entry zone
  * Look at the price scale on the right — read the exact numbers

- If it is a SIGNAL CARD (formatted text overlay on image):
  * Read ALL text carefully, including small print
  * Common layouts: Symbol at top, BUY/SELL prominent, then Entry/SL/TP below
  * Risk:Reward ratio may appear (e.g. "R:R 1:3")

- If it is an ORDER SCREENSHOT:
  * Read the order type (Buy Limit, Sell Stop, Buy Market, etc.)
  * Read SL and TP fields directly
  * Read the lot size / volume if shown
  * The symbol is usually shown in the order header

## Extraction rules:
1. Entry price: if a range is given (e.g. "1.0850-1.0870"), record BOTH as 
   entry_low and entry_high and set entry as the midpoint
2. Multiple TPs: record as tp1, tp2, tp3 etc. in order
3. Symbol normalization: strip spaces, convert to uppercase. 
   "Gold" → "XAUUSD", "Eur/Usd" → "EURUSD", "BTC" → "BTCUSD",
   "Nasdaq" → "NAS100", "Oil" → "XTIUSD", "Dow" → "US30"
4. Direction: BUY/LONG/UP/BULL all mean "buy". SELL/SHORT/DOWN/BEAR = "sell"
5. If entry is "market" or "now" or "current price", set entry_type = "market"
6. Lot size: only include if explicitly stated. Do NOT infer.
7. Risk percent: only include if explicitly stated (e.g. "risk 1%")
8. If a parameter cannot be found, use null — never invent values

## Response format (JSON only):
{
  "symbol": "EURUSD",
  "direction": "buy",
  "entry_type": "limit",
  "entry": 1.0850,
  "entry_low": 1.0840,
  "entry_high": 1.0860,
  "sl": 1.0800,
  "tp1": 1.0920,
  "tp2": 1.0980,
  "tp3": null,
  "lot_size": null,
  "risk_percent": null,
  "timeframe": "H4",
  "notes": "Provider said wait for candle close above 1.0850",
  "raw_symbol_text": "EUR/USD",
  "confidence": 0.92,
  "extraction_warnings": []
}
"""
```

### 6.3 Stage 3 — Update Parameter Extraction

**Triggered when** Stage 1 returns any update intent  
**Model preference:** Fast model is sufficient (text usually)

```python
UPDATE_EXTRACTION_PROMPT = """
You are parsing a trade UPDATE message. The trader has already entered a 
position and this message is modifying it.

## Recent trades this system has open:
{open_trades_json}

## Update message:
{message_text}

## Your task:
1. Identify WHICH open trade this update refers to (by symbol, or by position 
   in conversation)
2. Extract what action to take

## Possible update actions:
- move_sl_to_breakeven : Set SL = original entry price
- move_sl_to_price     : Set SL to a specific new price
- move_tp_to_price     : Set TP to a specific new price  
- close_partial        : Close X% or X lots of the position
- close_full           : Close the entire position now
- tp_hit_notification  : TP was hit (no action needed, just log)
- sl_hit_notification  : SL was hit (no action needed, just log)

## Response format (JSON only):
{
  "action": "move_sl_to_breakeven",
  "target_symbol": "EURUSD",
  "target_direction": "buy",
  "new_sl": null,
  "new_tp": null,
  "close_percent": null,
  "tp_level_hit": 1,
  "confidence": 0.88,
  "reasoning": "Message says 'move SL to entry' after TP1 on EURUSD buy"
}
"""
```

### 6.4 Stage 4 — Final Action Resolution

```python
# src/telegram_signal_copier/services/analyzer.py

from dataclasses import dataclass
from typing import Optional, List
from enum import Enum

class ActionType(str, Enum):
    OPEN_TRADE       = "open_trade"
    MODIFY_TRADE     = "modify_trade"
    CLOSE_TRADE      = "close_trade"
    CLOSE_PARTIAL    = "close_partial"
    LOG_ONLY         = "log_only"
    IGNORE           = "ignore"

@dataclass
class ResolvedAction:
    action_type: ActionType
    
    # For OPEN_TRADE
    symbol: Optional[str] = None
    direction: Optional[str] = None        # "buy" or "sell"
    entry_type: Optional[str] = None       # "market" or "limit" or "stop"
    entry_price: Optional[float] = None
    sl: Optional[float] = None
    tp1: Optional[float] = None
    tp2: Optional[float] = None
    tp3: Optional[float] = None
    lot_size: Optional[float] = None
    risk_percent: Optional[float] = None
    
    # For MODIFY_TRADE / CLOSE operations
    target_trade_id: Optional[str] = None  # internal ID of tracked open trade
    new_sl: Optional[float] = None
    new_tp: Optional[float] = None
    close_percent: Optional[float] = None
    
    # Metadata
    confidence: float = 0.0
    source_group_id: Optional[str] = None
    reasoning: Optional[str] = None
    skip_reason: Optional[str] = None
```

---

## 7. Open Trade State Tracker

The system must track all trades it has opened so update messages can reference them correctly.

```python
# src/telegram_signal_copier/services/trade_tracker.py

import json
import os
import time
from dataclasses import dataclass, field, asdict
from typing import Optional, List, Dict
import threading

@dataclass
class TrackedTrade:
    internal_id: str                    # UUID assigned by this system
    symbol: str
    direction: str                      # "buy" or "sell"
    entry_price: float
    sl: Optional[float]
    tp1: Optional[float]
    tp2: Optional[float]
    tp3: Optional[float]
    lot_size: float
    opened_at: float                    # Unix timestamp
    channel_id: int
    source_group_id: str                # MessageGroup that triggered this
    mt5_ticket: Optional[int] = None    # MT5 order ticket from .result file
    status: str = "open"                # open / partial / closed
    tp_levels_hit: List[int] = field(default_factory=list)
    notes: str = ""

class TradeTracker:
    """
    Persists open trade state to a JSON file so it survives restarts.
    Thread-safe via a lock.
    
    Storage: <MT5_FILES_PATH>/trade_tracker_state.json
    """

    def __init__(self, state_file: str):
        self._state_file = state_file
        self._lock = threading.Lock()
        self._trades: Dict[str, TrackedTrade] = {}
        self._load()

    def add_trade(self, trade: TrackedTrade) -> None:
        with self._lock:
            self._trades[trade.internal_id] = trade
            self._save()

    def find_by_symbol_and_direction(
        self, symbol: str, direction: str
    ) -> List[TrackedTrade]:
        with self._lock:
            return [
                t for t in self._trades.values()
                if t.symbol.upper() == symbol.upper()
                and t.direction == direction
                and t.status == "open"
            ]

    def find_most_recent_open(
        self, symbol: Optional[str] = None
    ) -> Optional[TrackedTrade]:
        with self._lock:
            candidates = [
                t for t in self._trades.values() if t.status == "open"
            ]
            if symbol:
                candidates = [
                    t for t in candidates 
                    if t.symbol.upper() == symbol.upper()
                ]
            if not candidates:
                return None
            return max(candidates, key=lambda t: t.opened_at)

    def update_trade(self, internal_id: str, **kwargs) -> None:
        with self._lock:
            if internal_id in self._trades:
                for k, v in kwargs.items():
                    setattr(self._trades[internal_id], k, v)
                self._save()

    def get_open_trades_summary(self) -> str:
        """Returns a JSON string suitable for injection into AI prompts."""
        with self._lock:
            open_trades = [
                {
                    "id": t.internal_id,
                    "symbol": t.symbol,
                    "direction": t.direction,
                    "entry": t.entry_price,
                    "sl": t.sl,
                    "tp1": t.tp1,
                    "tp2": t.tp2,
                    "lot_size": t.lot_size,
                    "opened_at": t.opened_at,
                    "tp_levels_hit": t.tp_levels_hit,
                    "status": t.status,
                }
                for t in self._trades.values()
                if t.status in ("open", "partial")
            ]
            return json.dumps(open_trades, indent=2)

    def _save(self) -> None:
        data = {k: asdict(v) for k, v in self._trades.items()}
        with open(self._state_file, "w") as f:
            json.dump(data, f, indent=2)

    def _load(self) -> None:
        if os.path.exists(self._state_file):
            with open(self._state_file) as f:
                data = json.load(f)
            self._trades = {
                k: TrackedTrade(**v) for k, v in data.items()
            }
```

---

## 8. Deduplication Guard

Prevents the same signal from triggering two trades (e.g. if a signal is forwarded, or arrives via two channels).

```python
# src/telegram_signal_copier/services/deduplication.py

import hashlib
import time
import json
from typing import Optional

class DeduplicationGuard:
    """
    Generates a fingerprint for each potential trade action and checks if
    it has already been acted on within the dedup window.
    
    Fingerprint components:
    - symbol (normalized)
    - direction (buy/sell)  
    - entry price (rounded to 4 decimal places)
    - sl price (rounded to 4 decimal places)
    
    Window: 4 hours by default (configurable via DEDUP_WINDOW_HOURS)
    Persistence: JSON file (survives restarts)
    """
    
    def __init__(self, store_file: str, window_hours: float = 4.0):
        self._store_file = store_file
        self._window_seconds = window_hours * 3600
        self._seen: dict[str, float] = {}  # fingerprint → timestamp
        self._load()

    def is_duplicate(self, symbol: str, direction: str,
                     entry: Optional[float], sl: Optional[float]) -> bool:
        fp = self._fingerprint(symbol, direction, entry, sl)
        if fp in self._seen:
            age = time.time() - self._seen[fp]
            return age < self._window_seconds
        return False

    def record(self, symbol: str, direction: str,
               entry: Optional[float], sl: Optional[float]) -> None:
        fp = self._fingerprint(symbol, direction, entry, sl)
        self._seen[fp] = time.time()
        self._evict_old()
        self._save()

    def _fingerprint(self, symbol: str, direction: str,
                     entry: Optional[float], sl: Optional[float]) -> str:
        key = {
            "s": symbol.upper(),
            "d": direction.lower(),
            "e": round(entry, 4) if entry else None,
            "sl": round(sl, 4) if sl else None,
        }
        return hashlib.sha256(
            json.dumps(key, sort_keys=True).encode()
        ).hexdigest()[:16]

    def _evict_old(self) -> None:
        cutoff = time.time() - self._window_seconds
        self._seen = {
            k: v for k, v in self._seen.items() if v >= cutoff
        }

    def _save(self) -> None:
        with open(self._store_file, "w") as f:
            json.dump(self._seen, f)

    def _load(self) -> None:
        try:
            with open(self._store_file) as f:
                self._seen = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            self._seen = {}
```

---

## 9. FileBridge Command Format (Complete)

```python
# src/telegram_signal_copier/adapters/bridge.py  (expanded)

"""
.cmd file format consumed by the MT5 EA:

=== OPEN TRADE ===
ACTION=OPEN
SYMBOL=EURUSDm
DIRECTION=BUY
TYPE=MARKET
ENTRY=0
SL=1.08000
TP1=1.09200
TP2=1.09800
TP3=0
LOT=0.10
MAGIC=12345
COMMENT=TG_SIGNAL_abc12345
TIMESTAMP=1715000000

=== MODIFY TRADE ===
ACTION=MODIFY
SYMBOL=EURUSDm
TICKET=123456789
NEW_SL=1.08500
NEW_TP=1.09500
TIMESTAMP=1715000001

=== CLOSE PARTIAL ===
ACTION=CLOSE_PARTIAL
SYMBOL=EURUSDm
TICKET=123456789
CLOSE_PERCENT=50
TIMESTAMP=1715000002

=== CLOSE FULL ===
ACTION=CLOSE_FULL
SYMBOL=EURUSDm
TICKET=123456789
TIMESTAMP=1715000003

=== MOVE BREAKEVEN ===
ACTION=MODIFY
SYMBOL=EURUSDm
TICKET=123456789
NEW_SL=BREAKEVEN
TIMESTAMP=1715000004
"""

import os
import time
import uuid
from pathlib import Path
from dataclasses import dataclass
from typing import Optional

class FileBridgeExecutor:
    
    def __init__(self, bridge_folder: str, symbol_suffix: str = ""):
        self.bridge_folder = Path(bridge_folder)
        self.symbol_suffix = symbol_suffix
        self.bridge_folder.mkdir(parents=True, exist_ok=True)

    def _symbol(self, base: str) -> str:
        base = base.upper().strip()
        if self.symbol_suffix and not base.endswith(self.symbol_suffix):
            return base + self.symbol_suffix
        return base

    def _write_cmd(self, lines: list[str]) -> str:
        """Write a .cmd file and return its path."""
        cmd_id = uuid.uuid4().hex[:12]
        path = self.bridge_folder / f"{cmd_id}.cmd"
        content = "\n".join(lines)
        path.write_text(content, encoding="utf-8")
        return str(path)

    def open_trade(
        self,
        symbol: str,
        direction: str,
        entry_type: str,
        entry_price: Optional[float],
        sl: Optional[float],
        tp1: Optional[float],
        tp2: Optional[float],
        tp3: Optional[float],
        lot_size: float,
        magic: int,
        internal_id: str,
    ) -> str:
        lines = [
            "ACTION=OPEN",
            f"SYMBOL={self._symbol(symbol)}",
            f"DIRECTION={direction.upper()}",
            f"TYPE={entry_type.upper()}",
            f"ENTRY={entry_price or 0}",
            f"SL={sl or 0}",
            f"TP1={tp1 or 0}",
            f"TP2={tp2 or 0}",
            f"TP3={tp3 or 0}",
            f"LOT={lot_size:.2f}",
            f"MAGIC={magic}",
            f"COMMENT=TG_{internal_id[:12]}",
            f"TIMESTAMP={int(time.time())}",
        ]
        return self._write_cmd(lines)

    def modify_trade(
        self,
        symbol: str,
        ticket: int,
        new_sl: Optional[float | str],  # float or "BREAKEVEN"
        new_tp: Optional[float],
    ) -> str:
        lines = [
            "ACTION=MODIFY",
            f"SYMBOL={self._symbol(symbol)}",
            f"TICKET={ticket}",
            f"NEW_SL={new_sl or 0}",
            f"NEW_TP={new_tp or 0}",
            f"TIMESTAMP={int(time.time())}",
        ]
        return self._write_cmd(lines)

    def close_partial(
        self, symbol: str, ticket: int, close_percent: float
    ) -> str:
        lines = [
            "ACTION=CLOSE_PARTIAL",
            f"SYMBOL={self._symbol(symbol)}",
            f"TICKET={ticket}",
            f"CLOSE_PERCENT={close_percent}",
            f"TIMESTAMP={int(time.time())}",
        ]
        return self._write_cmd(lines)

    def close_full(self, symbol: str, ticket: int) -> str:
        lines = [
            "ACTION=CLOSE_FULL",
            f"SYMBOL={self._symbol(symbol)}",
            f"TICKET={ticket}",
            f"TIMESTAMP={int(time.time())}",
        ]
        return self._write_cmd(lines)
```

---

## 10. Signal Examples and Expected Behavior

This section is critical for training/validating the AI classifier. Include new examples whenever edge cases are found.

### Example 1 — Plain text signal (simple)

```
Input text: "EURUSD BUY NOW
SL: 1.0800
TP1: 1.0920
TP2: 1.0980"

Expected intent:     new_trade_signal (confidence > 0.95)
Expected extraction:
  symbol:    EURUSD
  direction: buy
  entry:     market
  sl:        1.0800
  tp1:       1.0920
  tp2:       1.0980
Expected action:     OPEN_TRADE (market order)
```

### Example 2 — Chart image with long arrow

```
Input: <image showing XAUUSD H4 chart with upward arrow from ~2310 zone,
        horizontal line at 2290 labeled "SL", 
        horizontal line at 2370 labeled "TP">
No text.

Expected intent:     new_trade_signal (confidence ~0.85)
Expected extraction:
  symbol:    XAUUSD
  direction: buy
  entry:     ~2310 (from zone)
  sl:        2290
  tp1:       2370
Expected action:     OPEN_TRADE
Note: confidence slightly lower because entry zone is approximate
```

### Example 3 — Celebration / TP hit notification

```
Input text: "🎉🎉 TP1 HIT on EURUSD BUY! Move SL to breakeven now!"

Expected intent:     tp_hit + breakeven_move (combined)
Expected update extraction:
  tp_level_hit:   1
  action:         move_sl_to_breakeven
  target_symbol:  EURUSD
Expected action:     MODIFY_TRADE (set SL = entry of EURUSD buy)
```

### Example 4 — Multi-message pattern (Pattern E)

```
MSG 1 (T+0s):  "Watching GBPJPY closely"
MSG 2 (T+5s):  "Structure is very clear here"
MSG 3 (T+12s): <chart image of GBPJPY, annotated short arrow, SL above>
MSG 4 (T+25s): "SELL 193.50, SL 194.20, TP 192.00"

Group released at T+55s (30s after MSG 4)
Combined text for analysis: all 4 messages concatenated

Expected intent:     new_trade_signal
Expected extraction:
  symbol:    GBPJPY
  direction: sell
  entry:     193.50
  sl:        194.20
  tp1:       192.00
Expected action:     OPEN_TRADE (limit order at 193.50)
```

### Example 5 — Order screenshot only

```
Input: <MT5 terminal screenshot showing:
        Order #12345678
        Buy Limit EURUSD
        Price: 1.0850
        Stop Loss: 1.0790
        Take Profit: 1.0950
        Volume: 0.10>

Expected intent:     new_trade_signal (confidence 0.80)
Expected extraction:
  symbol:    EURUSD
  direction: buy
  entry:     1.0850
  entry_type: limit
  sl:        1.0790
  tp1:       1.0950
  lot_size:  0.10  (noted but risk engine may override)
Expected action:     OPEN_TRADE
Note: this is someone else's order screenshot being shared as a signal
```

### Example 6 — Pure commentary (no action)

```
Input text: "DXY is showing weakness on the weekly, I expect EUR strength 
             this week but waiting for confirmation before entering."

Expected intent:     market_commentary (confidence > 0.95)
Expected action:     IGNORE
```

### Example 7 — Ambiguous (needs more context)

```
MSG arrives: "Taking profit here"
No prior context in window, no symbol mentioned.

Expected intent:     ambiguous
Expected action:     LOG_ONLY (wait for next message or more context)
```

### Example 8 — SL modification

```
Input text: "EURUSD buyers, move your SL down to 1.0780, 
             market is giving us more room"

Expected intent:     sl_modification
Expected extraction:
  target_symbol: EURUSD
  target_direction: buy
  new_sl: 1.0780
Expected action:     MODIFY_TRADE on open EURUSD buy
```

---

## 11. Risk Engine Rules

```python
# src/telegram_signal_copier/services/risk_engine.py (complete spec)

"""
Risk Engine — Rules:

1. POSITION SIZING
   - Default: risk RISK_PERCENT_PER_TRADE % of account balance per trade
   - Formula: lot = (balance * risk_pct) / (sl_pips * pip_value)
   - If SL is not provided: use DEFAULT_SL_PIPS as fallback
   - If lot_size is explicitly provided in signal AND TRUST_SIGNAL_LOT_SIZE=true:
     use signal lot_size directly
   - Minimum lot: MAX(broker minimum, MIN_LOT_SIZE from config)
   - Maximum lot: MIN(broker maximum, MAX_LOT_SIZE from config)

2. SYMBOL VALIDATION
   - Strip broker suffix from signal symbol if present
   - Look up base symbol in allowed_symbols list
   - If not found AND auto_add_new_symbols=true: add to list
   - If not found AND auto_add_new_symbols=false: reject trade, log warning

3. DAILY LIMITS
   - MAX_TRADES_PER_DAY: reject if daily trade count reached
   - MAX_LOSS_PERCENT_PER_DAY: reject if daily drawdown % reached
   - SAME_SYMBOL_COOLDOWN_MINUTES: prevent opening same symbol twice within N min

4. DUPLICATE PREVENTION
   - Check DeduplicationGuard before opening any trade
   - Reject if fingerprint seen within DEDUP_WINDOW_HOURS

5. CONFIDENCE GATE
   - Reject any trade where AI confidence < AI_MIN_CONFIDENCE
   - Log rejection reason and confidence score

6. SL SANITY CHECKS
   - For BUY: SL must be BELOW entry price
   - For SELL: SL must be ABOVE entry price
   - If sanity check fails: reject trade, log error
   
7. TP SANITY CHECKS
   - For BUY: TP must be ABOVE entry price
   - For SELL: TP must be BELOW entry price
   - Multiple TPs must be in order (TP2 > TP1 for buy, TP2 < TP1 for sell)
"""
```

### Risk Engine Environment Variables

```ini
# Risk settings in .env

RISK_PERCENT_PER_TRADE=1.0      # Risk 1% of account per trade
MIN_LOT_SIZE=0.01
MAX_LOT_SIZE=5.0
DEFAULT_SL_PIPS=50              # Used when signal has no SL
TRUST_SIGNAL_LOT_SIZE=false     # Ignore signal's lot size, use risk %
MAX_TRADES_PER_DAY=10
MAX_LOSS_PERCENT_PER_DAY=5.0
SAME_SYMBOL_COOLDOWN_MINUTES=60
AI_MIN_CONFIDENCE=0.75
DEDUP_WINDOW_HOURS=4.0
AUTO_ADD_NEW_SYMBOLS=false
```

---

## 12. Complete Pipeline Wiring

```python
# src/telegram_signal_copier/main.py (complete wiring spec)

"""
Startup sequence:

1. Load .env
2. Build AIKeyPool from environment
3. Validate at least one API key is working (send test prompt)
4. Initialize FileBridge (check folder exists, is writable)
5. Initialize TradeTracker (load state from JSON)
6. Initialize DeduplicationGuard (load state from JSON)
7. Initialize MessageBuffer with release_callback
8. Start asyncio ticker task (calls buffer.tick() every 1 second)
9. Connect Telethon client
10. Register message handler for configured channel IDs
11. Write bridge status file (bridge_status.txt = READY)
12. Enter asyncio event loop

Message handler (called by Telethon on new message):
1. Download image bytes if message has photo
2. Create RawMessage object
3. Call buffer.ingest(raw_message)

Release callback (called by buffer when group is ready):
1. Get context history for channel
2. Build AnalysisRequest
3. Call Stage 1: classify_intent()
   - If IRRELEVANT or MARKET_COMMENTARY: log, return
   - If confidence < 0.5: log as ambiguous, return
4. If new_trade_signal:
   - Call Stage 2: extract_trade_parameters()
   - Call risk_engine.validate_and_size()
   - Call dedup_guard.is_duplicate()
   - If all pass: call bridge.open_trade()
   - Call trade_tracker.add_trade()
   - Call dedup_guard.record()
5. If update intent:
   - Call Stage 3: extract_update_parameters()
   - Look up target trade in trade_tracker
   - Call appropriate bridge method (modify/close/partial)
   - Update trade_tracker state
6. Log full analysis result to structured log file
"""
```

---

## 13. Logging and Observability

```python
# Every analysis decision must be logged with full detail

LOG_ENTRY_SCHEMA = {
    "timestamp": "ISO8601",
    "group_id": "uuid",
    "channel_id": "int",
    "message_count": "int",
    "image_count": "int",
    "stage1_intent": "MessageIntent",
    "stage1_confidence": "float",
    "stage1_reasoning": "str",
    "stage1_api_key_used": "str",
    "stage2_extraction": "TradeParameters | null",
    "stage2_confidence": "float",
    "stage2_api_key_used": "str",
    "stage3_update": "UpdateParameters | null",
    "risk_engine_result": "approved | rejected | str",
    "rejection_reason": "str | null",
    "action_taken": "ActionType",
    "cmd_file_written": "str | null",
    "lot_size": "float | null",
    "dedup_hit": "bool",
}

# Log file: logs/pipeline_YYYYMMDD.jsonl (one JSON object per line)
# This format allows easy analysis with jq, pandas, etc.
```

---

## 14. Testing the Pipeline Without Live MT5

```python
# tools/dry_run_test.py
# Run this to test the full pipeline without sending any .cmd files

"""
Usage:
  & ".venv/Scripts/python.exe" tools/dry_run_test.py --input tests/sample_messages.json

The tool feeds pre-recorded messages through the full pipeline and prints
what action WOULD have been taken, without writing any .cmd files.

Set DRY_RUN=true in .env to make the live system also skip .cmd writes.
"""
```

### Sample Test Messages File

```json
// tests/sample_messages.json
[
  {
    "test_id": "T001",
    "description": "Simple text signal",
    "messages": [
      {
        "text": "EURUSD BUY NOW\nSL: 1.0800\nTP1: 1.0920\nTP2: 1.0980",
        "has_image": false
      }
    ],
    "expected_intent": "new_trade_signal",
    "expected_action": "OPEN_TRADE",
    "expected_symbol": "EURUSD",
    "expected_direction": "buy"
  },
  {
    "test_id": "T002", 
    "description": "TP hit with breakeven instruction",
    "messages": [
      {
        "text": "🎉 TP1 HIT on EURUSD BUY! Move SL to breakeven!",
        "has_image": false
      }
    ],
    "prior_open_trades": [
      {
        "symbol": "EURUSD",
        "direction": "buy",
        "entry_price": 1.0850,
        "sl": 1.0800,
        "tp1": 1.0920
      }
    ],
    "expected_intent": "tp_hit",
    "expected_action": "MODIFY_TRADE",
    "expected_new_sl": "BREAKEVEN"
  },
  {
    "test_id": "T003",
    "description": "Pure commentary — no action",
    "messages": [
      {
        "text": "DXY showing weakness, EUR may strengthen this week",
        "has_image": false
      }
    ],
    "expected_intent": "market_commentary",
    "expected_action": "IGNORE"
  }
]
```

---

## 15. Pending Work Checklist

```
Core implementation:
[ ] Implement MessageBuffer (section 4.2) with asyncio tick loop
[ ] Implement AIKeyPool (section 5) with health/rate-limit tracking
[ ] Implement load_ai_key_pool() reading all provider env vars
[ ] Implement Stage 1 intent classifier calling AI with prompt
[ ] Implement Stage 2 trade parameter extractor with vision support
[ ] Implement Stage 3 update parameter extractor
[ ] Implement Stage 4 action resolver combining all stage outputs
[ ] Implement TradeTracker with JSON persistence
[ ] Implement DeduplicationGuard with JSON persistence
[ ] Expand FileBridgeExecutor with all command types (section 9)
[ ] Wire complete pipeline in main.py (section 12)
[ ] Implement risk engine full rules (section 11)

Signal intelligence:
[ ] Add symbol synonym map (Gold→XAUUSD, Nasdaq→NAS100, etc.)
[ ] Add OCR fallback for signal card images (pytesseract)
[ ] Add image description pre-processing (describe image before extraction)
[ ] Test and tune AI_MIN_CONFIDENCE threshold with real signal samples
[ ] Build test corpus from real channel messages (anonymized)

Operations:
[ ] Add dry_run_test.py tool (section 14)
[ ] Implement structured JSONL logging (section 13)
[ ] Add daily trade count / drawdown tracking
[ ] Add Telegram notification when trade is opened (optional bot message)
[ ] Add health check endpoint (simple HTTP or file-based)
[ ] Add graceful shutdown (flush buffer, save state)
[ ] Document MT5 EA changes required to handle all new .cmd ACTION types
```

---

## 16. MT5 EA Requirements

The MT5 Expert Advisor must be updated to handle all `ACTION` types defined in section 9. Key requirements:

```
ACTION=OPEN
  - Support TYPE=MARKET, LIMIT, STOP
  - Support TP2 and TP3 (open separate positions or use MT5 multi-TP logic)
  - Write ticket number back to .result file

ACTION=MODIFY
  - Support NEW_SL=BREAKEVEN (EA reads entry price of ticket and sets SL there)
  - Support NEW_SL=<price>
  - Support NEW_TP=<price>

ACTION=CLOSE_PARTIAL
  - Close CLOSE_PERCENT% of the position volume
  - Write confirmation to .result file

ACTION=CLOSE_FULL
  - Close entire position
  - Write confirmation to .result file

.result file format:
  CMD_ID=<original cmd filename without .cmd>
  STATUS=OK|ERROR
  TICKET=<MT5 ticket number>
  ERROR_CODE=<MT5 error code if STATUS=ERROR>
  ERROR_MSG=<human readable error if STATUS=ERROR>
  TIMESTAMP=<unix time>
```

---

*This document is the authoritative specification for the intelligent signal copier. Every implementation decision should reference back to this document. Update the Pending Work checklist as items are completed.*
