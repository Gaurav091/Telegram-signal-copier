---
argument-hint: agent
description: Refactor the Telegram Signal Copier codebase for maintainability and good practices without breaking any existing functionality.
---

# Refactor: Telegram Signal Copier

## Objective

Improve code quality, separation of concerns, and long-term maintainability of the `src/telegram_signal_copier/` package. **All existing behaviour must be preserved exactly.** No feature additions, no removals. Each change must be verifiable by the existing test suite passing.

---

## Scope

Work only inside `src/telegram_signal_copier/`, `tests/`, and `config.py`. Do not touch `tools/`, `packaging/`, `mt5/`, or build artefacts.

---

## Refactoring Areas (priority order)

### 1 · Extract a `constants.py` module

**Problem:** Hard-coded domain data is scattered across `risk_engine.py` and `signal_parser.py` as module-level dicts.

**Action:**
- Create `src/telegram_signal_copier/constants.py`.
- Move these into it:
  - `_SYMBOL_ALIASES` from `risk_engine.py`
  - `_SYMBOL_PRICE_RANGES` from `risk_engine.py`
  - `_SYMBOL_MIN_STOP` from `risk_engine.py`
  - `_SYMBOL_MIN_TP1_DISTANCE` from `risk_engine.py`
  - `_CRYPTO_ENTRY_MIN` from `signal_parser.py`
- Import them back in their original files so callers see no change.
- Give each dict a public name (no leading underscore) since they are module-level constants, not private state.

---

### 2 · Decompose `OpenAIClient`

**Problem:** `adapters/openai_client.py` conflates four responsibilities in one class: response caching, circuit-breaking, provider routing, and HTTP calls.

**Action:**
- Create `adapters/ai_cache.py` — `AIResponseCache` class.
  - Wraps the in-memory `dict` + optional `shelve` persistence.
  - Methods: `get(key) -> dict | None`, `put(key, value)`, `close()`.
- Create `adapters/circuit_breaker.py` — `CircuitBreaker` class.
  - Manages `failure_count`, `trip_until`, `disabled_until` per provider.
  - Methods: `is_open(provider_name) -> bool`, `record_failure(provider_name)`, `record_success(provider_name)`.
- Keep `OpenAIClient` in `openai_client.py` but reduce it to provider routing + HTTP dispatch, delegating to `AIResponseCache` and `CircuitBreaker`.
- All existing `OpenAIClient` public method signatures must remain identical.

---

### 3 · Isolate intent classification from `pipeline.py`

**Problem:** `CopierPipeline.process_message` contains inline intent heuristics (regex patterns + confidence thresholds) mixed with pipeline orchestration logic.

**Action:**
- Create `services/intent_classifier.py` — `IntentClassifier` class.
  - Move `_NEW_SIGNAL_OVERRIDE`, `_TRADE_UPDATE_OVERRIDE`, `_INFO_SKIP_THRESHOLD`, `_UPDATE_SKIP_THRESHOLD`, and the full intent-decision block into this class.
  - Single public method: `classify(text: str, has_images: bool) -> IntentResult` where `IntentResult` is a small `dataclass(slots=True)` with fields `intent: str`, `confidence: float`, `reasoning: str`, `force_skip: bool`.
- `CopierPipeline.__init__` receives an `IntentClassifier` instance (dependency injection).
- `process_message` calls `self._intent_classifier.classify(...)` and reads the returned dataclass.
- No behaviour change — only extraction.

---

### 4 · Tighten `config.py`

**Problem:** `config.py` hand-rolls dotenv parsing and uses raw `os.environ` everywhere, making it hard to test and error-prone.

**Action:**
- Replace the hand-rolled `_load_dotenv` with `python-dotenv`'s `load_dotenv` (already in many Python projects; add to `requirements.txt` if absent).
- Group the `_csv_env`, `_bool_env`, `_parse_source_spec` helpers into a private `_EnvReader` helper class (or a module-private namespace class) so the global namespace is cleaner.
- Add a top-level `validate()` method to `AppConfig` that runs all validation (currently `_validate_telegram_source_values` is a standalone function called externally) and raises a single `ConfigurationError(ValueError)` listing all issues at once instead of raising on the first bad value.
- `ConfigurationError` should be importable from `telegram_signal_copier.config`.

---

### 5 · Replace bare `except Exception` blocks

**Problem:** `bridge.py`, `openai_client.py`, and `main.py` use `except Exception: pass` and `except Exception: ...` that swallow errors silently.

**Action:**
- Every silent `except` must at minimum call `logger.debug("...", exc_info=True)` so failures are traceable in debug mode.
- Bare `except Exception: pass` with no logging is acceptable only for best-effort cleanup paths (temp-file unlink, lock release). Add a comment `# best-effort` to mark intentional suppression.
- Do not change the control-flow or retry behaviour — only add logging.

---

### 6 · Enforce consistent type annotations

**Problem:** Several methods use `dict` / `list` without generics, `Any` is imported but used loosely, and some return types are missing.

**Action:**
- Add return-type annotations to all public methods that lack them.
- Replace bare `dict` / `list` with `dict[str, X]` / `list[X]` in function signatures.
- Replace `Any` with the narrowest correct type where it is statically knowable. Keep `Any` only for truly dynamic payloads (e.g., raw JSON from LLM).
- Do not add annotations to private helper functions whose types are obvious from context.

---

### 7 · Improve test isolation

**Problem:** Existing tests in `tests/` import live service classes without dependency-injection seams, making mocking brittle.

**Action:**
- Ensure every service class (`SignalParser`, `RiskEngine`, `CopierPipeline`, `ImageProcessor`, `OpenAIClient`) accepts all its external collaborators via `__init__` parameters (no internal instantiation of collaborators).
- Update `tests/test_pipeline.py` and `tests/test_signal_parser.py` to construct dependencies explicitly rather than relying on `AppConfig` to build them.
- Add `pytest` fixtures for a minimal `AppConfig` (all defaults, no real credentials required) in `tests/conftest.py`.

---

### 8 · Module `__init__.py` hygiene

**Problem:** `src/telegram_signal_copier/__init__.py` may re-export symbols inconsistently.

**Action:**
- Ensure `__init__.py` exports only the public API: `AppConfig`, `TelegramSignalMessage`, `ParsedSignal`, `TradeCommand`, `ExecutionResult`.
- Add `__all__` listing those names.
- Do not add new public symbols — only tidy the list.

---

## Constraints

| Rule | Detail |
|------|--------|
| No new dependencies | Only add `python-dotenv` if absent. No other new packages. |
| No behaviour changes | All regex patterns, thresholds, retry logic, file-write logic must remain identical. |
| Backward-compatible imports | Any symbol moved to a new module must remain importable from its original module path via a re-export. |
| Tests must pass | Run `python -m pytest tests/ -x` after each area is complete. Fix any import breakage before moving on. |
| One PR per area | Deliver each numbered area as a separate commit with message `refactor: <area title>`. |

---

## Verification Checklist

After all areas are done, confirm:

- [ ] `python -m pytest tests/ -v` — all tests green
- [ ] `python -c "from telegram_signal_copier.config import AppConfig, ConfigurationError"` — no error
- [ ] `python -c "from telegram_signal_copier import TelegramSignalMessage, ParsedSignal"` — no error
- [ ] `python -c "from telegram_signal_copier.constants import SYMBOL_ALIASES"` — no error
- [ ] `python -c "from telegram_signal_copier.adapters.openai_client import OpenAIClient"` — no error
- [ ] Listener starts cleanly: `python -m telegram_signal_copier.main listen --dry-run` (if supported) or check startup log for no tracebacks
- [ ] No new `pylance` / `mypy` errors introduced (run `mypy src/ --ignore-missing-imports`)

---

## File Map (expected new / moved files)

```
src/telegram_signal_copier/
├── constants.py                   ← NEW  (area 1)
├── config.py                      ← MODIFIED (area 4)
├── __init__.py                    ← MODIFIED (area 8)
├── adapters/
│   ├── ai_cache.py                ← NEW  (area 2)
│   ├── circuit_breaker.py         ← NEW  (area 2)
│   ├── openai_client.py           ← MODIFIED (area 2)
│   ├── bridge.py                  ← MODIFIED (area 5 — add logging)
│   └── ...
├── services/
│   ├── intent_classifier.py       ← NEW  (area 3)
│   ├── pipeline.py                ← MODIFIED (area 3)
│   ├── risk_engine.py             ← MODIFIED (area 1 — import from constants)
│   ├── signal_parser.py           ← MODIFIED (area 1 — import from constants)
│   └── ...
└── models/
    └── ...
tests/
└── conftest.py                    ← NEW  (area 7)
```
