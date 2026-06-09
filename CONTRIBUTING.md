# Contributing & Module Standards

Standards for creating and modifying source files in this codebase.
Follow these rules to keep every module readable, testable, and maintainable.

---

## Table of Contents

1. [File Size Limit](#1-file-size-limit)
2. [Module Naming](#2-module-naming)
3. [File Structure Template](#3-file-structure-template)
4. [Import Rules](#4-import-rules)
5. [Public API & Backward Compatibility](#5-public-api--backward-compatibility)
6. [Adding a New Service](#6-adding-a-new-service)
7. [Adding a New Adapter](#7-adding-a-new-adapter)
8. [Adding a New Agent Node](#8-adding-a-new-agent-node)
9. [Configuration Variables](#9-configuration-variables)
10. [Testing Requirements](#10-testing-requirements)
11. [Splitting an Existing File](#11-splitting-an-existing-file)
12. [Commit Messages](#12-commit-messages)
13. [What NOT to Do](#13-what-not-to-do)

---

## 1. File Size Limit

**Hard limit: 300 lines per file.**

If adding code pushes a file past 300 lines, split it first (see §11).
No exceptions. Small files are easy to read, diff, and test in isolation.

---

## 2. Module Naming

| Layer | Package | Naming pattern | Example |
|---|---|---|---|
| Entry point | root | `main.py`, `config.py` | — |
| Config helpers | root | `config_helpers.py` | — |
| Listener subsystem | root | `listener_<noun>.py` | `listener_runner.py` |
| Data pipeline | `services/` | `<noun>.py` or `<noun>_<aspect>.py` | `signal_heuristic.py` |
| Signal parsing | `services/signals/` | `<aspect>.py` | `heuristic.py`, `ai_merge.py` |
| GUI panels | `gui/` | `<panel>_panel.py` or `<concern>.py` | `trades_panel.py`, `theme.py` |
| Setup wizard | `setup/` | `wizard_<aspect>.py` | `wizard_pages_core.py`, `wizard_shell.py` |
| External I/O | `adapters/` | `<target>.py` or `<target>_<aspect>.py` | `openai_prompts.py` |
| Agent nodes | `agents/` | `<role>_agent.py` or `<role>_agent_<aspect>.py` | `developer_agent_patch.py` |
| Shared types | `models/` | `<noun>.py` | `contracts.py` |

Rules:
- All lowercase, underscores only — no hyphens, no camelCase filenames.
- Name describes what the module **does**, not what it **is** (e.g. `heuristic` not `parser_utils`).
- Never create a generic `utils.py` or `helpers.py` at any level.
- When a directory grows past 5 modules, consider grouping into a subpackage with `__init__.py` re-exports.
- Subpackage `__init__.py` must re-export all public names for backward compatibility.

---

## 3. File Structure Template

Every new `.py` file must follow this order:

```python
"""One-sentence module description.

Optional: 2–4 line explanation of what lives here and what does not.
Cross-reference related modules if useful.
"""
from __future__ import annotations

# ── Standard library ──────────────────────────────────────────────────────────
import logging
import re
from pathlib import Path
from typing import Any

# ── Third-party ───────────────────────────────────────────────────────────────
# (only if truly needed — prefer stdlib)

# ── Internal ──────────────────────────────────────────────────────────────────
from telegram_signal_copier.config import AppConfig
from telegram_signal_copier.models import SomeModel

logger = logging.getLogger(__name__)

# ── Constants / module-level data ─────────────────────────────────────────────
SOME_CONSTANT = "value"

# ── Public functions / classes ────────────────────────────────────────────────

def public_function(...) -> ...:
    ...

class PublicClass:
    ...

# ── Private helpers (only if they don't fit elsewhere) ───────────────────────

def _internal_helper(...) -> ...:
    ...
```

Rules:
- Module docstring is **mandatory** — one sentence minimum.
- `from __future__ import annotations` is always first (enables deferred type hints).
- Import groups separated by a blank line: stdlib → third-party → internal.
- One `logger = logging.getLogger(__name__)` per file, near the top.
- No `print()` in library code — use `logger.info/debug/warning/error`.

---

## 4. Import Rules

**Absolute imports only.** Never use relative imports (`from . import ...`).

```python
# CORRECT
from telegram_signal_copier.services.signal_patterns import PRICE_PATTERN

# WRONG
from .signal_patterns import PRICE_PATTERN
```

**Avoid circular imports.** The dependency graph must be a DAG:

```
models  ←  config  ←  config_helpers
  ↓            ↓
services    adapters    agents
  ↑              ↑         ↑
          (no back-edges)
```

If a circular import is unavoidable, use a **deferred import** inside the function body:

```python
def my_func():
    from telegram_signal_copier.services.foo import bar  # deferred — breaks cycle
    return bar(...)
```

**TYPE_CHECKING guard** for type-only imports that would create cycles:

```python
from __future__ import annotations
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from telegram_signal_copier.config import AppConfig
```

---

## 5. Public API & Backward Compatibility

When splitting a file, the original module must re-export every name that was previously public:

```python
# old_module.py — after split
# Keep these so existing callers don't break:
from telegram_signal_copier.services.new_module import public_func as public_func  # noqa: F401
from telegram_signal_copier.services.new_module import PublicClass as PublicClass  # noqa: F401
```

Backward-compat wrappers for static methods that tests may call directly:

```python
class MyClass:
    @staticmethod
    def _legacy_name(x: str) -> str:
        return new_standalone_function(x)
```

---

## 6. Adding a New Service

Services live in `src/telegram_signal_copier/services/`.
A service encapsulates a business logic concern (parsing, classification, deduplication, etc.).

Checklist:
- [ ] File ≤ 300 lines
- [ ] Module docstring explains scope
- [ ] No direct I/O (file reads/writes belong in adapters)
- [ ] No `import telegram_signal_copier.adapters.*` inside services (keep layers clean)
- [ ] Pure functions preferred over stateful classes where possible
- [ ] Add at least one test in `tests/test_<service_name>.py`
- [ ] Export from `services/__init__.py` only if the name is part of the public API

### Example: adding `services/signal_volume.py`

```python
"""Volume inference from signal text.

Extracts lot-size hints from messages like 'risk 1%' or 'open 0.02 lot'.
Does NOT access config directly — receives allowed range as arguments.
"""
from __future__ import annotations

import re
import logging

logger = logging.getLogger(__name__)

_LOT_PATTERN = re.compile(r"\b(\d+(?:\.\d+)?)\s*lot", re.IGNORECASE)


def infer_volume(text: str, default: float = 0.01) -> float:
    """Return the first lot size found in text, or default."""
    m = _LOT_PATTERN.search(text)
    if m:
        return float(m.group(1))
    return default
```

---

## 7. Adding a New Adapter

Adapters live in `src/telegram_signal_copier/adapters/`.
An adapter wraps external I/O: HTTP APIs, file system, OS calls.

Checklist:
- [ ] File ≤ 300 lines
- [ ] All network calls have a timeout (`timeout=10` minimum)
- [ ] No `aiohttp` or `urllib.request` — use `requests` with `timeout=10, verify=False` (SSL hangs on this machine)
- [ ] Errors are caught and re-raised as domain exceptions or logged — never silently swallowed
- [ ] Circuit-breaker / retry logic for external services (reuse `adapters/circuit_breaker.py`)
- [ ] Cache expensive calls where possible (reuse `adapters/ai_cache.py`)
- [ ] Add provider-specific logic in `adapters/provider_adapters.py`, not in `openai_client.py`

### Example: adding a new AI provider adapter

1. Add a class in `adapters/provider_adapters.py` implementing `.post(path, payload) -> dict` and `.probe() -> bool`.
2. Register it in the `get_adapter()` factory at the bottom of that file.
3. No changes needed to `openai_client.py`.

---

## 8. Adding a New Agent Node

Agent nodes live in `src/telegram_signal_copier/agents/`.
Each node is a pure function: `(state: AgentState) -> dict[str, Any]`.

```python
def my_agent_node(state: AgentState, *, my_dependency: SomeType) -> dict[str, Any]:
    """One sentence: what this node does."""
    # ... process state ...
    return {
        "some_field": result,
        "next_node": "validate",   # or "reject" / "end"
    }
```

Checklist:
- [ ] Function signature: first arg is `AgentState`, keyword-only extra deps via `*`
- [ ] Always returns a `dict` — never mutates `state` directly
- [ ] Sets `next_node` to control pipeline routing
- [ ] Wire into `build_graph()` in `agents/graph.py` via `functools.partial`
- [ ] Add the new node name to the `nodes` dict in `build_graph()`

---

## 9. Configuration Variables

All `.env` variables are defined in `config.py` as fields on `AppConfig`.
Parsing/loading helpers go in `config_helpers.py`.

Rules:
- One field per variable — no `**kwargs` or dict-based configs.
- Defaults must be **safe for production** (e.g. `dry_run=False`, not `True`).
- New fields must appear in the `.env` example block in `README.md`.
- Use `_bool_env()` / `_csv_env()` helpers from `config_helpers.py` — never `os.environ.get(...) == "true"` inline.
- Optional fields use `field(default=None)` and are typed `str | None`.

```python
# In AppConfig (config.py):
my_new_feature_enabled: bool = field(default_factory=lambda: _bool_env("MY_NEW_FEATURE", False))
```

---

## 10. Testing Requirements

Test files live in `tests/`.
File naming: `tests/test_<module_name>.py`.

Minimum coverage for any new module:
- At least one happy-path test
- At least one edge/error-path test
- No real network calls in tests (mock or stub all adapters)
- No real file I/O in tests (use `tmp_path` or `tempfile.TemporaryDirectory`)

Run tests before committing:

```powershell
& ".venv\Scripts\python.exe" -m pytest tests/ -q
```

All 50 existing tests must continue to pass after any change.

---

## 11. Splitting an Existing File

When a file exceeds 300 lines:

1. **Identify cohesive groups** of functions/classes — group by what they operate on, not by size.
2. **Create the new file** with the extracted code. Use `create_file`, never delete-and-recreate.
3. **Add re-exports** to the original file for every name that was public.
4. **Update imports** in any file that imported from the original (use grep/search to find all callers).
5. **Run tests** — all must pass before committing.
6. **One logical split per commit** — don't bundle multiple splits together.

### Naming the new file

| What you're extracting | Suffix convention |
|---|---|
| Regex / compiled patterns | `patterns.py` (in subpackage) or `_patterns.py` |
| Pure normalizer functions | `normalizers.py` (in subpackage) or `_normalizers.py` |
| Heuristic / rule-based logic | `heuristic.py` |
| AI merge / payload processing | `ai_merge.py` |
| UI panel (Flet/tkinter) | `<name>_panel.py` |
| Dialog / modal UI | `dialogs.py` |
| Theme / styling constants | `theme.py` |
| Wizard page classes | `wizard_pages.py` or `wizard_pages_<group>.py` |
| Wizard shell / navigation | `wizard_shell.py` |
| Launcher / entry window | `launcher.py` |
| Config/env helpers | `wizard_helpers.py` or `config_helpers.py` |
| Prompt / template strings | `_prompts.py` |
| Data models / dataclasses | `_models.py` |
| Analysis / classification logic | `_analysis.py` |

### Creating a subpackage

When splitting creates 3+ related files, create a subpackage:

1. Create directory: `services/signals/`, `gui/`, `setup/`
2. Create `__init__.py` that re-exports all public names
3. Replace original monolith with thin facade that imports from subpackage
4. All external imports continue working unchanged

Example facade (`gui.py` after extraction):
```python
"""Backward-compatible facade — delegates to gui/ subpackage."""
from __future__ import annotations
from telegram_signal_copier.gui.dashboard import SignalCopierDashboard as SignalCopierDashboard  # noqa: F401
```

---

## 12. Commit Messages

Format: `<type>(<scope>): <subject>`

| Type | When to use |
|---|---|
| `feat` | New feature or new public function |
| `fix` | Bug fix |
| `refactor` | Code restructuring — no behaviour change |
| `test` | Tests only |
| `docs` | Documentation only |
| `chore` | Tooling, config, deps |

Examples:
```
feat(pipeline): add partial-close detection stage
fix(bridge): handle missing outbox dir on first run
refactor(signal_parser): split normalizers into signal_normalizers.py
docs(README): update key-files reference for new modules
test(signal_heuristic): add MT5 screenshot parse edge cases
```

Scope = the module or subsystem being changed (e.g. `pipeline`, `bridge`, `config`).

---

## 13. What NOT to Do

| Anti-pattern | Why | Alternative |
|---|---|---|
| Generic `utils.py` | Becomes a dumping ground | Name by what the functions do |
| `from module import *` | Breaks static analysis | Explicit imports only |
| `print()` in library code | Not controllable | `logger.info/debug/warning` |
| Relative imports (`from . import`) | Fragile on refactor | Absolute imports only |
| Silently swallowing exceptions (`except: pass`) | Hides bugs | At minimum `logger.debug(..., exc_info=True)` |
| Mutable default arguments | Classic Python gotcha | Use `None` + guard inside |
| Business logic in `main.py` | Untestable | Move to service/adapter, call from `main.py` |
| Hard-coded paths | Breaks on other machines | Use `config.project_root / "subpath"` |
| `aiohttp` or `urllib.request` for HTTP | Hangs on SSL on this machine | `requests` with `timeout=10, verify=False` |
| File over 300 lines | Hard to review and test | Split before adding more code |
| Monolith class > 300 lines | God object anti-pattern | Extract methods into focused modules/classes |
| Stale extracted modules | Drift from main code | Update extracted modules when fixing bugs in monolith |
| Storing secrets in source | Security risk | `.env` file only, never committed |
