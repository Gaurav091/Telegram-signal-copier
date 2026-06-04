## project fast-facts

**Stack:** Python 3.11, Telethon, MetaTrader5 (MT5), OpenAI/Groq, asyncio pipeline  
**Entry point:** `src/telegram_signal_copier/main.py`  
**Venv:** `.venv\Scripts\python.exe`  
**Config:** `.env` (root) — holds API keys, `TELEGRAM_SOURCES`, symbol whitelist, risk params  
**Runtime files:** `runtime/listener.pid`, `runtime/listener.lock`, `runtime/sessions/`  
**Logs:** `logs/pipeline_YYYY-MM-DD.jsonl` — one JSON record per processed message  
**Pipeline flow:** Telegram msg → cluster_agent → intent_classifier → signal_parser → validation_agent → executor (MT5)  
**Key source dirs:**  
- `src/telegram_signal_copier/` — all app code  
- `src/telegram_signal_copier/agents/` — agent modules (pipeline, execution, extraction, validation)  
- `src/telegram_signal_copier/signal/` — heuristic + AI parsers  
- `tools/` — standalone diagnostic/query scripts (run directly with venv python)  

**Common tool scripts (run with `.venv\Scripts\python.exe tools/<script>.py`):**  
- `_mt5_group_profits.py` — P&L by source group, last 10 days, from MT5 deal history  
- `_find_fgmk.py` — find FGMK group signals  
- `_find_new_groups*.py` — discover unmapped Telegram channels  
- `search_mt5_logs.py` — search MT5 journal logs  

**MT5 deal comments format:** `TG|<SLUG>|<msg_id>` where SLUG = first 15 chars of group name, uppercased, spaces→hyphens  
**SLUG_TO_NAME map** lives in `tools/_mt5_group_profits.py` — update when adding new groups  

## trade analysis policy

When user asks about trade performance, losses, profits, group stats:

1. Run `tools/_mt5_group_profits.py` directly — it pulls live MT5 history and prints ranked P&L table.
2. Do NOT parse pipeline JSONL logs for P&L — MT5 deal history is authoritative.
3. For per-signal detail, query `logs/pipeline_YYYY-MM-DD.jsonl` filtering by `source_group` and `action_taken: "FILLED"`.
4. Loss groups = negative `profit_by_channel`. Win rate < 50% AND negative P&L = candidate to disable.
5. To disable a group: remove or comment its entry from `TELEGRAM_SOURCES` in `.env`, then restart listener.

## graphify

For any repository question in chat, use Graphify first.

Workflow:
1. If `graphify-out/graph.json` is missing, run `graphify update .` first.
2. If graph is older than recent source edits, run `graphify update .` first.
3. Then run `graphify query "<user question>"` as first retrieval step.
4. Use `graphify path "<A>" "<B>"` for relationship/dependency questions.
5. Use `graphify explain "<concept>"` for focused concept overviews.

Default behavior: do this before broad file scans/grep/semantic search, unless user asks to skip Graphify.

Triggers: "how do I…", "where is…", "what does … do", "add/modify a <component>",
"explain the architecture", or anything that depends on how files or classes relate.

If `graphify-out/wiki/index.md` exists, use it for broad navigation. Read `graphify-out/GRAPH_REPORT.md`
only for broad architecture review or when query/path/explain do not surface enough context. Only read
source files when (a) modifying/debugging specific code, (b) the graph lacks the needed detail, or
(c) the graph is missing or stale.

Type `/graphify` in Copilot Chat to build or update the graph manually.

## listener restart policy

When user asks to restart listener:

1. Use visible VS Code terminal foreground command, not detached/background launch:
	- `& ".\\.venv\\Scripts\\python.exe" -u -m telegram_signal_copier.main listen`
2. If output shows `Listener already running`:
	- `Get-Process -Name python,TelegramSignalCopier -ErrorAction SilentlyContinue | Stop-Process -Force`
	- `Remove-Item .\\runtime\\listener.lock -ErrorAction SilentlyContinue`
	- `Remove-Item .\\runtime\\listener.pid -ErrorAction SilentlyContinue`
	- run foreground listener command again.
3. Keep listener attached so logs stay visible in terminal.

## fix implementation policy

When asked to fix an issue:

1. Preserve existing behavior and integrations unless the user explicitly asks to change or remove them.
2. Implement fixes additively on top of current functionality, minimizing regression risk.
3. Prefer targeted patches with verification over broad rewrites.

## channel mapping policy

When user asks to check/fix/add Telegram source channel mapping:

1. Resolve and map sources using numeric chat ID only (for channel `-100XXXXXXXXXX`, map value as `XXXXXXXXXX`).
2. Do not use title text or username as the mapping target value in `TELEGRAM_SOURCES`.
3. If multiple similar channel names exist, verify by matching recent message text before applying mapping.
4. After mapping update, restart listener and verify bridge source map reflects the numeric ID.
