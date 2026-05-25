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
