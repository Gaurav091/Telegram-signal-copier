# Graph Report - Telegram signal Copier  (2026-05-25)

## Corpus Check
- 118 files · ~5,368,632 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 1074 nodes · 1784 edges · 117 communities (97 shown, 20 thin omitted)
- Extraction: 77% EXTRACTED · 23% INFERRED · 0% AMBIGUOUS · INFERRED: 412 edges (avg confidence: 0.72)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `a6c43185`
- Run `git rev-parse HEAD` and compare to check if the graph is stale.
- Run `graphify update .` after code changes (no API cost).

## Community Hubs (Navigation)
- [[_COMMUNITY_Community 0|Community 0]]
- [[_COMMUNITY_Community 1|Community 1]]
- [[_COMMUNITY_Community 2|Community 2]]
- [[_COMMUNITY_Community 3|Community 3]]
- [[_COMMUNITY_Community 4|Community 4]]
- [[_COMMUNITY_Community 5|Community 5]]
- [[_COMMUNITY_Community 6|Community 6]]
- [[_COMMUNITY_Community 7|Community 7]]
- [[_COMMUNITY_Community 8|Community 8]]
- [[_COMMUNITY_Community 9|Community 9]]
- [[_COMMUNITY_Community 10|Community 10]]
- [[_COMMUNITY_Community 11|Community 11]]
- [[_COMMUNITY_Community 12|Community 12]]
- [[_COMMUNITY_Community 13|Community 13]]
- [[_COMMUNITY_Community 14|Community 14]]
- [[_COMMUNITY_Community 15|Community 15]]
- [[_COMMUNITY_Community 16|Community 16]]
- [[_COMMUNITY_Community 17|Community 17]]
- [[_COMMUNITY_Community 18|Community 18]]
- [[_COMMUNITY_Community 19|Community 19]]
- [[_COMMUNITY_Community 20|Community 20]]
- [[_COMMUNITY_Community 21|Community 21]]
- [[_COMMUNITY_Community 22|Community 22]]
- [[_COMMUNITY_Community 23|Community 23]]
- [[_COMMUNITY_Community 24|Community 24]]
- [[_COMMUNITY_Community 25|Community 25]]
- [[_COMMUNITY_Community 26|Community 26]]
- [[_COMMUNITY_Community 27|Community 27]]
- [[_COMMUNITY_Community 28|Community 28]]
- [[_COMMUNITY_Community 29|Community 29]]
- [[_COMMUNITY_Community 30|Community 30]]
- [[_COMMUNITY_Community 31|Community 31]]
- [[_COMMUNITY_Community 32|Community 32]]
- [[_COMMUNITY_Community 33|Community 33]]
- [[_COMMUNITY_Community 34|Community 34]]
- [[_COMMUNITY_Community 35|Community 35]]
- [[_COMMUNITY_Community 36|Community 36]]
- [[_COMMUNITY_Community 37|Community 37]]
- [[_COMMUNITY_Community 38|Community 38]]
- [[_COMMUNITY_Community 39|Community 39]]
- [[_COMMUNITY_Community 40|Community 40]]
- [[_COMMUNITY_Community 41|Community 41]]
- [[_COMMUNITY_Community 42|Community 42]]
- [[_COMMUNITY_Community 43|Community 43]]
- [[_COMMUNITY_Community 44|Community 44]]
- [[_COMMUNITY_Community 45|Community 45]]
- [[_COMMUNITY_Community 46|Community 46]]
- [[_COMMUNITY_Community 47|Community 47]]
- [[_COMMUNITY_Community 48|Community 48]]
- [[_COMMUNITY_Community 49|Community 49]]
- [[_COMMUNITY_Community 50|Community 50]]
- [[_COMMUNITY_Community 51|Community 51]]
- [[_COMMUNITY_Community 52|Community 52]]
- [[_COMMUNITY_Community 53|Community 53]]
- [[_COMMUNITY_Community 54|Community 54]]
- [[_COMMUNITY_Community 55|Community 55]]
- [[_COMMUNITY_Community 56|Community 56]]
- [[_COMMUNITY_Community 57|Community 57]]
- [[_COMMUNITY_Community 58|Community 58]]
- [[_COMMUNITY_Community 59|Community 59]]
- [[_COMMUNITY_Community 61|Community 61]]
- [[_COMMUNITY_Community 62|Community 62]]
- [[_COMMUNITY_Community 63|Community 63]]
- [[_COMMUNITY_Community 64|Community 64]]
- [[_COMMUNITY_Community 65|Community 65]]
- [[_COMMUNITY_Community 66|Community 66]]
- [[_COMMUNITY_Community 67|Community 67]]
- [[_COMMUNITY_Community 68|Community 68]]
- [[_COMMUNITY_Community 69|Community 69]]
- [[_COMMUNITY_Community 70|Community 70]]
- [[_COMMUNITY_Community 71|Community 71]]
- [[_COMMUNITY_Community 72|Community 72]]
- [[_COMMUNITY_Community 73|Community 73]]
- [[_COMMUNITY_Community 74|Community 74]]
- [[_COMMUNITY_Community 75|Community 75]]
- [[_COMMUNITY_Community 76|Community 76]]
- [[_COMMUNITY_Community 77|Community 77]]
- [[_COMMUNITY_Community 80|Community 80]]
- [[_COMMUNITY_Community 81|Community 81]]
- [[_COMMUNITY_Community 82|Community 82]]
- [[_COMMUNITY_Community 83|Community 83]]
- [[_COMMUNITY_Community 84|Community 84]]
- [[_COMMUNITY_Community 85|Community 85]]
- [[_COMMUNITY_Community 86|Community 86]]
- [[_COMMUNITY_Community 87|Community 87]]
- [[_COMMUNITY_Community 117|Community 117]]
- [[_COMMUNITY_Community 119|Community 119]]

## God Nodes (most connected - your core abstractions)
1. `PATH` - 63 edges
2. `AppConfig` - 42 edges
3. `SignalParser` - 38 edges
4. `OpenAIClient` - 37 edges
5. `RiskEngine` - 33 edges
6. `FileBridgeExecutor` - 32 edges
7. `CopierPipeline` - 31 edges
8. `Telegram Signal Copier` - 31 edges
9. `TelegramSignalMessage` - 30 edges
10. `PipelineTests` - 28 edges

## Surprising Connections (you probably didn't know these)
- `dynamic_symbols_path()` --calls--> `PATH`  [INFERRED]
  src/telegram_signal_copier/config.py → .vscode/settings.json
- `mt5_terminals()` --calls--> `PATH`  [INFERRED]
  tools/scan_mt5_logs.py → .vscode/settings.json
- `run()` --calls--> `run_on_message()`  [INFERRED]
  tools/test_agents.py → src/telegram_signal_copier/agents/graph.py
- `_run_with_restarts()` --calls--> `type`  [INFERRED]
  src/telegram_signal_copier/main.py → .vscode/mcp.json
- `main()` --calls--> `type`  [INFERRED]
  tools/dry_run_test.py → .vscode/mcp.json

## Communities (117 total, 20 thin omitted)

### Community 0 - "Community 0"
Cohesion: 0.05
Nodes (42): ExecutionResult, ParsedSignal, Return deduplicated list of all available images, primary first., TelegramSignalMessage, ImageProcessingResult, ImageProcessor, _payload_to_text(), _score_ocr_text() (+34 more)

### Community 1 - "Community 1"
Cohesion: 0.06
Nodes (55): apply_patch(), assess_false_positives(), _build_false_positive_prompt(), _build_prompt(), _call_llm(), classify_failures(), FailureReport, FalsePositiveReport (+47 more)

### Community 2 - "Community 2"
Cohesion: 0.04
Nodes (44): Auto-Fix Actions, BLOCKED → Listener Offline, BLOCKED → Stale Commands, code:block1 (┌───────────────────────────────────────────────────────────), code:json ({), code:json ({), code:json ({), code:bash (# Tail live verdicts) (+36 more)

### Community 3 - "Community 3"
Cohesion: 0.08
Nodes (18): _combine(), _FloodWaitSkip, MessageBuffer, _normalize_source_name(), _patched_platform_uname_for_telethon(), _prepare_telethon_ssl_runtime(), Groups messages from the same source channel within a rolling time window., NFKD-normalize + casefold a source name for comparison.      NFKD compatibilit (+10 more)

### Community 4 - "Community 4"
Cohesion: 0.06
Nodes (35): 1 — Install dependencies, 2 — Start the listener, 3 — Validate OCR (optional), 4 — Fix SSL warning (if needed), Change Log, `.cmd` files appear but no `.result` files, code:block1 (src/telegram_signal_copier/), code:powershell (& ".venv\Scripts\python.exe" -m pip install pyOpenSSL) (+27 more)

### Community 5 - "Community 5"
Cohesion: 0.18
Nodes (23): _acquire_listener_lock(), _bridge_root_path(), build_arg_parser(), build_pipeline(), _clear_listener_pid(), configure_logging(), _listener_lock_path(), _listener_pid_path() (+15 more)

### Community 6 - "Community 6"
Cohesion: 0.12
Nodes (11): _image_data_url(), _json_from_text(), OpenAIClient, Classify message intent before deciding how to process it.          Returns a, AI orchestration client with provider adapters, caching, rate-limiting, and circ, Parse a trading signal from text and/or chart image(s)., Patch, A proposed code change. (+3 more)

### Community 7 - "Community 7"
Cohesion: 0.15
Nodes (28): _age(), _append_autofix_log(), _append_daily_health_report(), bold(), _cleanup_stale_smoke_cmds(), _color(), cyan(), _daily_report_path() (+20 more)

### Community 8 - "Community 8"
Cohesion: 0.09
Nodes (22): AI Providers and OCR Setup, Architecture Overview, Build Plan, code:text (Telegram Groups / Channels), code:block16 (# Standard text signal), code:bash (# 1. Clone the repository), Configuration Needed, Core Goal (+14 more)

### Community 9 - "Community 9"
Cohesion: 0.13
Nodes (13): _bool_env(), _csv_env(), _default_bridge_root(), _default_project_root(), _dotenv_candidates(), dynamic_symbols_path(), from_env(), _load_dotenv() (+5 more)

### Community 10 - "Community 10"
Cohesion: 0.10
Nodes (12): MessageBuffer, MessageGroup, Message grouping buffer.  Collects incoming RawMessage objects from the Teleth, Add a raw message to the appropriate pending group., Release groups that are ready.  Call once per second from an asyncio task., Return recently released groups for this channel (for AI context injection)., Coroutine that calls ``buffer.tick()`` every ``interval_seconds``.      Run as, Wrapper around a Telethon message with extracted metadata. (+4 more)

### Community 11 - "Community 11"
Cohesion: 0.13
Nodes (15): auto_derive_sl(), ClusterSignal, _detect_side_and_order_type(), _detect_symbol(), MessageClusterAgent, parse_cluster(), _parse_price_list(), MessageClusterAgent — Context-aware multi-message signal assembler.  Behavior (+7 more)

### Community 12 - "Community 12"
Cohesion: 0.15
Nodes (11): TelegramIdentity, TelegramSessionService, _get_service(), Get current Telegram MCP connection status and signed-in account info., List Telegram chats, groups, and channels available to the signed-in account., Get recent messages from a Telegram dialog.      Args:         chat: Telegram, Send a message to a Telegram dialog.      Args:         chat: Telegram userna, telegram_connection_status() (+3 more)

### Community 13 - "Community 13"
Cohesion: 0.12
Nodes (9): Trade state tracker with JSON persistence.  Keeps a record of every trade open, JSON string suitable for injection into AI prompts., Write state to disk atomically.  Must be called while holding self._lock., Remove closed trades older than ``keep_days`` days.  Returns count removed., A single trade opened by the signal copier., Manages open trade state with JSON-file persistence.      Usage::          t, Update fields on a tracked trade.  Returns True if the trade was found., TrackedTrade (+1 more)

### Community 14 - "Community 14"
Cohesion: 0.22
Nodes (10): _age_from_epoch(), _latest_listener_log(), main(), _now_epoch(), _now_utc_str(), _parse_log_ts(), _read_kv(), Snapshot (+2 more)

### Community 15 - "Community 15"
Cohesion: 0.19
Nodes (10): CerebrasAdapter, CloudflareAdapter, get_adapter(), GroqAdapter, _normalize_message_content(), NvidiaAdapter, OpenAIAdapter, ProviderAdapter (+2 more)

### Community 16 - "Community 16"
Cohesion: 0.11
Nodes (18): 12. Complete Pipeline Wiring, 13. Logging and Observability, 15. Pending Work Checklist, 16. MT5 EA Requirements, 1. Project Goal (Plain English), 2. High-Level Architecture, 7. Open Trade State Tracker, 8. Deduplication Guard (+10 more)

### Community 17 - "Community 17"
Cohesion: 0.12
Nodes (17): 10. Signal Examples and Expected Behavior, code:block16 (Input text: "EURUSD BUY NOW), code:block17 (Input: <image showing XAUUSD H4 chart with upward arrow from), code:block18 (Input text: "🎉🎉 TP1 HIT on EURUSD BUY! Move SL to breakeven ), code:block19 (MSG 1 (T+0s):  "Watching GBPJPY closely"), code:block20 (Input: <MT5 terminal screenshot showing:), code:block21 (Input text: "DXY is showing weakness on the weekly, I expect), code:block22 (MSG arrives: "Taking profit here") (+9 more)

### Community 18 - "Community 18"
Cohesion: 0.13
Nodes (10): str, _probe(), Run exact same flow as the real listener and log all exceptions., _probe(), Minimal diagnostic: connect to Telegram, print any exception verbosely., main(), norm(), Find IDs of newly-joined Telegram groups. Uses a temporary copy of the session (+2 more)

### Community 19 - "Community 19"
Cohesion: 0.20
Nodes (10): ExtractedSignal, from_dict(), _maybe_float(), model_validate(), OrderType, Agent schemas — pure stdlib dataclasses, no external dependencies.  Replaces t, Raw signal as extracted by the LLM from unstructured text.      All fields are, RejectionReason (+2 more)

### Community 20 - "Community 20"
Cohesion: 0.17
Nodes (12): build_graph(), Agent pipeline — stdlib-only replacement for langgraph.StateGraph.  Graph topolo, Build and return the agent pipeline., Synchronously invoke the graph for a single message., Async Telethon listener that feeds incoming messages into the graph., run_on_message(), start_listener(), AgentState (+4 more)

### Community 21 - "Community 21"
Cohesion: 0.18
Nodes (12): _build_messages(), _encode_image(), extraction_agent_node(), Ingestion & Extraction Agent with vision support.  Handles both text-only signal, LangGraph node: extract structured trade signal from text and/or chart image., Return (base64_data, mime_type) for a local image file., Build LangChain message list with optional inline images., intent_filter_node() (+4 more)

### Community 22 - "Community 22"
Cohesion: 0.25
Nodes (13): daemon_loop(), _dedupe_processes(), _is_relevant(), _kill_pid(), _ps_all_process_map(), _ps_workspace_python_processes(), _ps_workspace_shell_processes(), Return list of dicts: {'pid': int, 'cmd': str} for shell processes (powershell/p (+5 more)

### Community 23 - "Community 23"
Cohesion: 0.21
Nodes (7): DeduplicationGuard, _fingerprint(), Signal deduplication guard with JSON persistence.  Prevents the same trade sig, Remove expired fingerprints from the in-memory store., Fingerprint-based duplicate signal detector.      Usage::          guard = D, Return True if this signal fingerprint was seen within the window., Record a signal fingerprint as acted-upon.

### Community 24 - "Community 24"
Cohesion: 0.28
Nodes (8): _clear_stale_cmds(), LogMonitorAgent, main(), All log files to monitor., Return only lines whose timestamp falls within the last window_seconds., _recent_lines(), _restart_listener(), _tail()

### Community 25 - "Community 25"
Cohesion: 0.67
Nodes (3): _build_llm(), main(), Entry-point: run the LangGraph multi-agent Telegram trade copier.  Usage ----

### Community 26 - "Community 26"
Cohesion: 0.20
Nodes (8): Stdlib-only LLM shim — drop-in replacement for langchain_openai.ChatOpenAI.  W, Minimal response wrapper exposing ``.content`` (mirrors langchain AIMessage)., Normalise a message to an OpenAI ``{"role": ..., "content": ...}`` dict., Stdlib replacement for ``langchain_openai.ChatOpenAI``.      Delegates all HTT, Call the LLM and return a response with a ``.content`` attribute.          Par, _Response, SimpleLLM, _to_openai_msg()

### Community 27 - "Community 27"
Cohesion: 0.21
Nodes (7): get(), init(), Raw Telegram message logger.  Writes every message received from a configured, Return the singleton (None if not yet initialised)., Thread-safe daily-rotating JSONL logger for raw Telegram messages., Initialise the module-level singleton and return it., RawMessageLogger

### Community 28 - "Community 28"
Cohesion: 0.23
Nodes (6): PipelineLogger, Structured JSONL pipeline logging (AGENT_SPEC section 13).  Every analysis dec, Return an open file handle, rotating if the UTC date changed., Convert Pydantic models or dataclasses to plain dicts for JSON., Thread-safe JSONL pipeline event logger with daily file rotation., _serialize()

### Community 29 - "Community 29"
Cohesion: 0.20
Nodes (8): _append_queue_entry(), FileBridgeExecutor, Send a MODIFY command to the MT5 EA.          ``new_sl`` may be a price (float, Send a CLOSE_PARTIAL command.  ``close_percent`` must be 0 < x ≤ 100., Send a CLOSE_FULL command to close the entire position., _should_retry_symbol_selection(), _strip_symbol_suffix(), _write_command_file()

### Community 30 - "Community 30"
Cohesion: 0.22
Nodes (8): check(), fail(), ok(), Tests for intent filter, vision handling, and image-type classification.  Run:, Make mock LLM return intent JSON for the intent_filter node., Queue multiple LLM responses in order., set_intent_response(), set_sequence()

### Community 31 - "Community 31"
Cohesion: 0.29
Nodes (5): _canonical_symbol(), _resolve_min_stop(), _resolve_min_tp1_distance(), _resolve_price_range(), _strip_broker_suffix()

### Community 32 - "Community 32"
Cohesion: 0.20
Nodes (10): After install, Build, code:text (%APPDATA%\TelegramSignalCopier), code:env (TELEGRAM_SIGNAL_COPIER_HOME=C:\TelegramSignalCopierData), code:powershell (.venv\Scripts\Activate.ps1), code:powershell (powershell -ExecutionPolicy Bypass -File packaging\build_win), Installed runtime path, Outputs (+2 more)

### Community 33 - "Community 33"
Cohesion: 0.18
Nodes (10): chat.tools.terminal.autoApprove, /^Set-Location \"d:\\\\Github repos\\\\Telegram signal Copier\"; \\$env:PYTHONPATH=\"src\"; C:/Users/HP/AppData/Local/Programs/Python/Python314/python\\.exe -m compileall src tests; C:/Users/HP/AppData/Local/Programs/Python/Python314/python\\.exe -m telegram_signal_copier sample --text \"BUY GOLD NOW @ 2320 SL 2315 TP1 2330 TP2 2338\"$/, /^Set-Location \"d:\\\\Github repos\\\\Telegram signal Copier\"; \\$env:PYTHONPATH=\"src\"; C:/Users/HP/AppData/Local/Programs/Python/Python314/python\\.exe -m pytest -q$/, python.envFile, python.terminal.useEnvFile, approve, matchCommandLine, approve (+2 more)

### Community 34 - "Community 34"
Cohesion: 0.22
Nodes (9): 6.1 Stage 1 — Intent Classification, 6.2 Stage 2 — Trade Parameter Extraction, 6.3 Stage 3 — Update Parameter Extraction, 6.4 Stage 4 — Final Action Resolution, 6. AI Analysis Pipeline — Four Stages, code:python (EXTRACTION_PROMPT = """), code:python (UPDATE_EXTRACTION_PROMPT = """), code:python (# src/telegram_signal_copier/services/analyzer.py) (+1 more)

### Community 35 - "Community 35"
Cohesion: 0.22
Nodes (9): `api_or_dashboard`, `image_processor`, `mt5_ea`, `mt5_executor`, Recommended Modules, `risk_engine`, `signal_parser`, `storage` (+1 more)

### Community 37 - "Community 37"
Cohesion: 0.29
Nodes (9): Broker-ready payload produced by the Risk & Validation Agent., ValidatedSignal, _canonical_symbol(), _fingerprint(), Risk & Validation Agent., LangGraph node: validate and enrich the extracted signal., _rr_ratio(), _strip_suffix() (+1 more)

### Community 38 - "Community 38"
Cohesion: 0.27
Nodes (7): _comment_source_slug(), from_bridge_lines(), from_signal(), _iso_to_epoch_text(), _normalize_text(), _now_iso(), TradeCommand

### Community 39 - "Community 39"
Cohesion: 0.39
Nodes (6): _hook(), log(), _logged__exit(), _logged_sys_exit(), _on_atexit(), Debug runner: enable Telethon DEBUG logging and faulthandler, capture full trace

### Community 40 - "Community 40"
Cohesion: 0.32
Nodes (3): _hook(), Ultra-minimal listener test: run _run_with_restarts for 60s and log everything., Tee

### Community 41 - "Community 41"
Cohesion: 0.29
Nodes (7): 5.1 API Key Pool Configuration, 5.2 Environment Configuration for Multiple Keys, 5.3 Loading API Keys from Environment, 5. Multi-API Key Orchestrator, code:python (# src/telegram_signal_copier/adapters/ai_pool.py), code:ini (# .env — configure as many keys as needed), code:python (# src/telegram_signal_copier/config.py  (addition))

### Community 42 - "Community 42"
Cohesion: 0.33
Nodes (3): _Pipeline, Sequential pipeline that routes via ``state.next_node``.      Replaces ``langgra, Run the pipeline synchronously and return the final state.

### Community 43 - "Community 43"
Cohesion: 0.38
Nodes (5): check(), fail(), ok(), Comprehensive end-to-end test for the multi-agent LangGraph pipeline.  Run:, run()

### Community 44 - "Community 44"
Cohesion: 0.20
Nodes (10): AI vision circuit breaker tripped, code:powershell (winget install --id ShiningLight.OpenSSL.Light --exact --acc), "Command volume must be greater than zero", EA not picking up commands, `Failed to load SSL library` on Windows startup, "Invalid stops" errors, Suggested System Architecture, Telegram OTP / session expired (+2 more)

### Community 45 - "Community 45"
Cohesion: 0.29
Nodes (7): 1. Telegram Integration, 2. Signal Intake, 3. AI Signal Analysis, 4. Validation Layer, 5. MT5 Trade Execution via EA Bridge, 6. Monitoring and Audit, Main Features

### Community 46 - "Community 46"
Cohesion: 0.29
Nodes (7): code:block10 (Telegram Signal Copier EA), code:powershell (# Copy source to MT5 Experts folder and compile), MT5 Expert Advisor Setup, Step 1 — Compile the EA, Step 2 — Attach to a chart, Step 3 — EA input parameters, Step 4 — Verify the bridge is working

### Community 47 - "Community 47"
Cohesion: 0.47
Nodes (5): _check_expectations(), main(), Dry-run pipeline tester (section 14 of AGENT_SPEC.md).  Feeds pre-recorded mes, Map final AgentState to a simplified action label., _resolve_action()

### Community 48 - "Community 48"
Cohesion: 0.40
Nodes (5): _build_trade_command(), execution_agent_node(), MT5 Execution Agent.  Translates a ``ValidatedSignal`` into a ``TradeCommand``, Convert a ValidatedSignal into the TradeCommand the bridge understands., LangGraph node: submit trade to MT5 via the file bridge.

### Community 49 - "Community 49"
Cohesion: 0.53
Nodes (5): find_logs_dir_from_status(), main(), parse_status(), Continuous MT5 log watcher.  Watches the MT5 terminal logs for lines mentionin, watch()

### Community 50 - "Community 50"
Cohesion: 0.40
Nodes (5): 3.1 Message Intent Categories, 3.2 Image Sub-Types, 3. Message Classification System, code:python (class MessageIntent(str, Enum):), code:python (class ImageType(str, Enum):)

### Community 51 - "Community 51"
Cohesion: 0.40
Nodes (5): 4.1 Why Grouping Is Required, 4.2 MessageBuffer Implementation, 4. Message Grouping and Context Window, code:block4 (Pattern A — Single text message:), code:python (# src/telegram_signal_copier/services/message_buffer.py)

### Community 52 - "Community 52"
Cohesion: 0.40
Nodes (5): code:block13 (Message received), code:block14 (request_id=abc-123), code:block15 (request_id=abc-123), How Signals Are Processed, MT5 Bridge file format

### Community 54 - "Community 54"
Cohesion: 0.60
Nodes (4): main(), parse_cmd(), Bridge autofix daemon: watches bridge folder and writes simulated .result for un, write_result()

### Community 55 - "Community 55"
Cohesion: 0.50
Nodes (3): Supervisor to run and restart required background processes.  Starts: - Teleg, start_proc(), supervise()

### Community 56 - "Community 56"
Cohesion: 0.50
Nodes (4): 11. Risk Engine Rules, code:python (# src/telegram_signal_copier/services/risk_engine.py (comple), code:ini (# Risk settings in .env), Risk Engine Environment Variables

### Community 57 - "Community 57"
Cohesion: 0.50
Nodes (4): 14. Testing the Pipeline Without Live MT5, code:python (# tools/dry_run_test.py), code:json (// tests/sample_messages.json), Sample Test Messages File

### Community 58 - "Community 58"
Cohesion: 0.67
Nodes (3): main(), norm(), Find IDs of newly-joined Telegram groups using StringSession (no file lock).

### Community 59 - "Community 59"
Cohesion: 0.20
Nodes (9): watch, PYTHONPATH, servers, telegramDesktop, args, command, dev, env (+1 more)

### Community 61 - "Community 61"
Cohesion: 0.50
Nodes (4): code:bash (# Activate venv first), code:powershell (python tools\supervisor.py), Keeping it running (Windows — optional), Running the Listener

### Community 62 - "Community 62"
Cohesion: 0.50
Nodes (4): code:env (# ─── Telegram ─────────────────────────────────────────────), code:bash (python -m telegram_signal_copier), Configuration (.env), First-time Telegram authentication

### Community 63 - "Community 63"
Cohesion: 0.67
Nodes (3): main(), parse_status(), Watch EA status file and bridge inbox for activity.  Prints changes to ea_stat

### Community 64 - "Community 64"
Cohesion: 0.67
Nodes (3): main(), norm(), Find IDs of newly-joined Telegram groups. Writes to _find_new_groups_result.txt.

### Community 65 - "Community 65"
Cohesion: 0.67
Nodes (3): main(), norm(), One-shot script to find IDs of the 4 newly-joined Telegram groups.

### Community 66 - "Community 66"
Cohesion: 0.67
Nodes (3): failing_task(), Test that our custom exception handler prevents sys.exit on background task fail, test()

### Community 67 - "Community 67"
Cohesion: 0.22
Nodes (9): code:text (Telegram Groups/Channels), code:json ({), code:powershell (python -m telegram_signal_copier login), code:powershell (python -m telegram_signal_copier sample --text "BUY GOLD NOW), Example AI Output Schema, Quick Start, Sample Local Run, Telegram Login (+1 more)

### Community 68 - "Community 68"
Cohesion: 0.29
Nodes (6): _probe(), Resolve all configured sources and print results + errors., bad_task(), main(), Test: does SystemExit in a background asyncio task propagate through run_until_c, type

### Community 117 - "Community 117"
Cohesion: 0.50
Nodes (3): inputs, tasks, version

## Knowledge Gaps
- **151 isolated node(s):** `command`, `args`, `PYTHONPATH`, `envFile`, `watch` (+146 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **20 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `PATH` connect `Community 0` to `Community 1`, `Community 3`, `Community 6`, `Community 7`, `Community 9`, `Community 13`, `Community 18`, `Community 21`, `Community 23`, `Community 25`, `Community 27`, `Community 28`, `Community 33`, `Community 47`, `Community 49`, `Community 58`, `Community 64`, `Community 65`, `Community 69`?**
  _High betweenness centrality (0.161) - this node is a cross-community bridge._
- **Why does `AppConfig` connect `Community 0` to `Community 1`, `Community 3`, `Community 6`, `Community 40`, `Community 9`, `Community 42`, `Community 12`, `Community 15`?**
  _High betweenness centrality (0.137) - this node is a cross-community bridge._
- **Why does `OpenAIClient` connect `Community 6` to `Community 0`, `Community 1`, `Community 5`, `Community 15`, `Community 20`, `Community 25`, `Community 26`?**
  _High betweenness centrality (0.052) - this node is a cross-community bridge._
- **Are the 68 inferred relationships involving `str` (e.g. with `from_env()` and `_status_file_content()`) actually correct?**
  _`str` has 68 INFERRED edges - model-reasoned connections that need verification._
- **Are the 62 inferred relationships involving `PATH` (e.g. with `_default_bridge_root()` and `_default_project_root()`) actually correct?**
  _`PATH` has 62 INFERRED edges - model-reasoned connections that need verification._
- **Are the 36 inferred relationships involving `AppConfig` (e.g. with `OpenAIClient` and `ProviderAdapter`) actually correct?**
  _`AppConfig` has 36 INFERRED edges - model-reasoned connections that need verification._
- **Are the 28 inferred relationships involving `SignalParser` (e.g. with `PipelineOutcome` and `CopierPipeline`) actually correct?**
  _`SignalParser` has 28 INFERRED edges - model-reasoned connections that need verification._