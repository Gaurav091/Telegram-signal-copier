#!/usr/bin/env python3
"""
Prompt booster — enriches any raw prompt with role, CoT, format constraints,
and limitations request.  Ships as both a CLI tool and a Python library.

CLI usage:
    python tools/deepseek_booster.py "your prompt"
    echo "compare Python and Java" | python tools/deepseek_booster.py
    python tools/deepseek_booster.py --task DECISION -- "Should I buy solar?"
    python tools/deepseek_booster.py --file prompt.txt --output enriched.txt
    python tools/deepseek_booster.py --print -- "write a poem about AI"

Python usage:
    from tools.deepseek_booster import build_enriched_prompt

    raw = "Compare Python and Java for web development"
    task = detect_task_type(raw)        # "ANALYSIS"
    enriched = build_enriched_prompt(raw, task, refine=True)
    print(enriched)                     # ready to send to any LLM

Env vars:
    DEEPSEEK_API_KEY       API key for DeepSeek cloud
    BOOSTER_MODEL          Model name (default: deepseek-chat)
    BOOSTER_TEMPERATURE    LLM temperature (default: 0.3)
    BOOSTER_MAX_TOKENS     Max response length (default: 2048)
    DEEPSEEK_USE_OLLAMA    Set "true" to use local Ollama
    OLLAMA_MODEL           Ollama model name (default: deepseek-flash:latest)
"""
from __future__ import annotations

import json
import os
import sys
import textwrap
from typing import Any

try:
    import requests
except ImportError:
    requests = None  # type: ignore[assignment]


# ======================== CONFIGURATION ========================
DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
DEEPSEEK_API_URL = "https://api.deepseek.com/v1/chat/completions"
DEFAULT_MODEL = os.environ.get("BOOSTER_MODEL", "deepseek-chat")
DEFAULT_TEMPERATURE = float(os.environ.get("BOOSTER_TEMPERATURE", "0.3"))
DEFAULT_MAX_TOKENS = int(os.environ.get("BOOSTER_MAX_TOKENS", "2048"))
# ===============================================================


# ---------------------------------------------------------------------------
# Boosting engine
# ---------------------------------------------------------------------------

def _has_word(lower: str, word: str) -> bool:
    """True if *word* appears as a standalone token in *lower*."""
    i = lower.find(word)
    while i != -1:
        left_ok = i == 0 or not lower[i - 1].isalnum()
        right_ok = i + len(word) == len(lower) or not lower[i + len(word)].isalnum()
        if left_ok and right_ok:
            return True
        i = lower.find(word, i + 1)
    return False


def detect_task_type(prompt: str) -> str:
    """Auto-detect the task category from prompt keywords."""
    lower = prompt.lower()

    # CODE (checked before CREATIVE so "write a function" → CODE, not CREATIVE)
    if any(_has_word(lower, w) for w in
           ["code", "function", "implement", "bug", "debug",
            "refactor", "class", "api"]):
        return "CODE"

    # DECISION (all keywords lowercase for case-sensitive find)
    if any(_has_word(lower, w) for w in
           ["should i", "which one", "best option", "recommend",
            "decision", "choose between", "what to pick"]):
        return "DECISION"

    # ANALYSIS
    if any(_has_word(lower, w) for w in
           ["compare", "versus", "vs", "difference",
            "pros", "cons", "advantages", "disadvantages",
            "analyse", "analyze", "evaluate", "assessment"]):
        return "ANALYSIS"

    # INSTRUCTION (all keywords lowercase)
    if any(_has_word(lower, w) for w in
           ["how to", "steps to", "guide me", "tutorial",
            "walkthrough", "instructions for", "steps"]):
        return "INSTRUCTION"

    # FACTUAL (all keywords lowercase)
    if any(_has_word(lower, w) for w in
           ["what is", "what are", "define", "explain",
            "meaning of", "definition", "facts about"]):
        return "FACTUAL"

    # CREATIVE
    if any(_has_word(lower, w) for w in
           ["write", "story", "poem", "creative", "fiction",
            "imagine", "describe", "narrative"]):
        return "CREATIVE"

    return "GENERAL"


def format_spec_for(task_type: str) -> str:
    specs = {
        "ANALYSIS": (
            "- **Comparison table** (rows: feature, column A, column B, winner)\n"
            "- **Key differences** (bullet list, 3-5 items)\n"
            "- **Recommendation** (which to choose and why)\n"
            "- **Limitations** (assumptions, edge cases)"
        ),
        "CREATIVE": (
            "- **Setting / premise** (1-2 sentences)\n"
            "- **Characters / elements** (bullet list)\n"
            "- **Main body** — vivid, specific, avoids cliché (min 150 words)\n"
            "- **Theme / takeaway** (1 sentence)\n"
            "- **Limitations** (what was left out or assumed)"
        ),
        "CODE": (
            "- **Approach** (algorithm / architecture, 2-3 sentences)\n"
            "- **Code** (complete, runnable, with imports)\n"
            "- **Complexity** (time & space)\n"
            "- **Edge cases** (what could go wrong)\n"
            "- **Limitations** (assumptions, version constraints)"
        ),
        "DECISION": (
            "- **Options** (bullet list with key attributes each)\n"
            "- **Decision criteria** (what matters most, weighted)\n"
            "- **Trade-offs** (what you gain vs what you lose per option)\n"
            "- **Final verdict** (one sentence recommendation)\n"
            "- **Limitations** (what was not considered)"
        ),
        "INSTRUCTION": (
            "- **Prerequisites** (tools, knowledge, permissions needed)\n"
            "- **Step-by-step** (numbered, each step 1-2 sentences)\n"
            "- **Expected outcome** (what success looks like)\n"
            "- **Troubleshooting** (common pitfalls)\n"
            "- **Limitations** (scope, version, platform assumptions)"
        ),
        "FACTUAL": (
            "- **Core answer** (1-2 sentences, direct)\n"
            "- **Evidence** (data points, sources, or reasoning)\n"
            "- **Context** (how this fits into the bigger picture)\n"
            "- **Limitations** (what is unknown or disputed)"
        ),
        "GENERAL": (
            "- **Key points** (bullet list, 3-5 items)\n"
            "- **Detailed explanation** (at least 4 sentences, evidence-based)\n"
            "- **Conclusion** (one sentence, actionable)\n"
            "- **Limitations** (missing information, assumptions)"
        ),
    }
    return specs.get(task_type, specs["GENERAL"])


def build_enriched_prompt(
    raw_prompt: str,
    task_type: str | None = None,
    *,
    extra_context: str = "",
    refine: bool = False,
) -> str:
    """Build a fully enriched (boosted) prompt string.

    Parameters
    ----------
    raw_prompt : str
        The user's original question or instruction.
    task_type : str or None
        Explicit task type. If None, auto-detect.
    extra_context : str
        Additional context to inject into the booster.
    refine : bool
        If True, append a self-refinement instruction block
        (for use with a two-pass workflow).

    Returns
    -------
    str — the enriched prompt, ready to send to any LLM.
    """
    if task_type is None:
        task_type = detect_task_type(raw_prompt)
    fmt = format_spec_for(task_type)
    context = f"\nContext:\n{extra_context}\n" if extra_context else ""
    refine_block = (
        "\n\nAfter your first answer, review it for 3 specific flaws "
        "(factual errors, omissions, lack of clarity, missing nuance, "
        "insufficient evidence). Then produce an improved version "
        "that fixes all three. Keep the same section structure."
        if refine else ""
    )

    return (
        "You are an expert AI assistant with deep knowledge across all domains. "
        "Your answers are clear, structured, precise, and evidence-based.\n\n"
        "Before writing the final answer, think step by step inside <thinking> tags. "
        "Be honest about uncertainty — if the question has no definitive answer, say so.\n\n"
        f"Task type: {task_type}\n\n"
        "Output format (follow this exactly):\n"
        f"{fmt}\n"
        "RULES:\n"
        "- Use specific numbers, names, and facts — never vague generalities.\n"
        '- Avoid weasel words: "might", "perhaps", "maybe", "could", "I think".\n'
        '- Avoid filler phrases: "in conclusion", "it is important to note", "overall".\n'
        '- If the data is genuinely insufficient, state "Insufficient data" and stop.\n'
        '- Never use first-person ("I believe", "my analysis").\n'
        "- Every factual claim must be defensible. If you cite, give the source inline.\n"
        f"{context}"
        f"{refine_block}\n\n"
        f"Now answer this prompt: {raw_prompt}"
    )


# Alias for backward compatibility
boost_prompt = build_enriched_prompt


# ---------------------------------------------------------------------------
# Backends
# ---------------------------------------------------------------------------

def call_deepseek_api(prompt: str, model: str = DEFAULT_MODEL,
                      temperature: float = DEFAULT_TEMPERATURE,
                      max_tokens: int = DEFAULT_MAX_TOKENS) -> str:
    if not DEEPSEEK_API_KEY:
        return "ERROR: DEEPSEEK_API_KEY not set."
    if requests is None:
        return "ERROR: `requests` not installed."
    headers = {"Authorization": f"Bearer {DEEPSEEK_API_KEY}", "Content-Type": "application/json"}
    payload: dict[str, Any] = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": temperature,
        "max_tokens": max_tokens,
        "stream": False,
    }
    try:
        resp = requests.post(DEEPSEEK_API_URL, headers=headers, json=payload, timeout=120)
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"].strip()
    except Exception as e:
        return f"ERROR calling DeepSeek API: {e}"


def call_openai_compat(prompt: str, api_key: str, base_url: str, model: str,
                       temperature: float = DEFAULT_TEMPERATURE,
                       max_tokens: int = DEFAULT_MAX_TOKENS) -> str:
    if requests is None:
        return "ERROR: `requests` not installed."
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": temperature,
        "max_tokens": max_tokens,
        "stream": False,
    }
    try:
        resp = requests.post(f"{base_url.rstrip('/')}/v1/chat/completions",
                             headers=headers, json=payload, timeout=120)
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"].strip()
    except Exception as e:
        return f"ERROR calling {base_url}: {e}"


def call_local_ollama(prompt: str, model: str = "deepseek-flash:latest",
                      temperature: float = DEFAULT_TEMPERATURE,
                      max_tokens: int = DEFAULT_MAX_TOKENS) -> str:
    if requests is None:
        return "ERROR: `requests` not installed."
    url = "http://localhost:11434/api/generate"
    payload = {
        "model": model,
        "prompt": prompt,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "stream": False,
    }
    try:
        resp = requests.post(url, json=payload, timeout=300)
        resp.raise_for_status()
        return resp.json()["response"].strip()
    except requests.exceptions.ConnectionError:
        return "ERROR: Cannot reach Ollama. Is it running? (ollama serve)"
    except Exception as e:
        return f"ERROR calling Ollama: {e}"


# ---------------------------------------------------------------------------
# Self-refinement loop
# ---------------------------------------------------------------------------

def refine_answer(raw_prompt: str, first_answer: str,
                  backend, **backend_kw) -> str:
    refinement_prompt = (
        f"You are a critical reviewer. The following answer was generated for:\n\n"
        f'PROMPT: "{raw_prompt}"\n\n'
        f"ANSWER TO REVIEW:\n{first_answer}\n\n"
        "Identify 3 specific flaws (factual errors, omissions, lack of clarity, "
        "missing nuance, insufficient evidence). Then produce an improved version "
        "that fixes all three. Keep the same section structure as the original answer."
    )
    return backend(refinement_prompt, **backend_kw)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def print_help() -> None:
    print(textwrap.dedent("""\
        Usage:
          python tools/deepseek_booster.py [OPTIONS] "your prompt"
          echo "your prompt" | python tools/deepseek_booster.py [OPTIONS]
          python tools/deepseek_booster.py [OPTIONS] --file prompt.txt

        Options:
          --task TYPE       Force task type: ANALYSIS | CREATIVE | CODE
                            | DECISION | INSTRUCTION | FACTUAL | GENERAL
          --model NAME      Model name (default: deepseek-chat)
          --api-key KEY     DeepSeek API key (env: DEEPSEEK_API_KEY)
          --ollama          Use local Ollama instead of DeepSeek API
          --ollama-model    Ollama model name (default: deepseek-flash:latest)
          --openai URL      Use any OpenAI-compatible endpoint
          --openai-key KEY  API key for --openai endpoint
          --openai-model    Model at --openai endpoint (default: deepseek-chat)
          --refine          Two-pass self-refinement (slower, higher quality)
          --print           Only print the boosted prompt — no API call.
                            Copy-paste into Freebuff, OpenCode, ChatGPT, etc.
          --file PATH       Read prompt from file (use "-" for stdin)
          --output PATH     Write response to file instead of stdout
          --json            Output raw JSON with metadata
          --temp FLOAT      Temperature (default: 0.3)
          --max-tokens N    Max tokens (default: 2048)
          --context TEXT    Extra context to inject into the booster
          --help            This message

        Examples:
          ask "Is solar worth it?"
          ask --refine "Explain monads in 3 sentences"
          ask --print "write a Python function"    # just print boosted text
          ask --task DECISION "Should I buy solar panels?"
          cat notes.txt | ask                       # pipe from stdin
          ask --file input.txt --output output.txt  # file in, file out
          ask --ollama "Compare Go vs Rust"
    """))


def _read_prompt_from_stdin() -> str | None:
    """Read prompt from stdin when piped (not a terminal)."""
    if not sys.stdin.isatty():
        try:
            return sys.stdin.read().strip()
        except Exception:
            return None
    return None


def main() -> None:
    args = [a for a in sys.argv[1:] if a not in ("-u", "-E", "-c", "-m")]

    if not args or args[0] in ("--help", "-h"):
        print_help()
        sys.exit(0 if args and args[0] == "--help" else 1)

    # --- defaults ---
    model = DEFAULT_MODEL
    api_key = DEEPSEEK_API_KEY
    use_ollama = os.environ.get("DEEPSEEK_USE_OLLAMA", "").lower() in ("1", "true", "yes")
    ollama_model = os.environ.get("OLLAMA_MODEL", "deepseek-flash:latest")
    openai_url = ""
    openai_key = ""
    openai_model = "deepseek-chat"
    do_refine = False
    print_only = False
    json_output = False
    temperature = DEFAULT_TEMPERATURE
    max_tokens = DEFAULT_MAX_TOKENS
    extra_context = ""
    explicit_task: str | None = None
    file_input: str | None = None
    file_output: str | None = None

    i = 0
    prompt_parts: list[str] = []
    while i < len(args):
        a = args[i]
        if a == "--task" and i + 1 < len(args):
            explicit_task = args[i + 1].upper()
            i += 2
        elif a == "--model" and i + 1 < len(args):
            model = args[i + 1]
            i += 2
        elif a == "--api-key" and i + 1 < len(args):
            api_key = args[i + 1]
            i += 2
        elif a == "--ollama":
            use_ollama = True
            i += 1
        elif a == "--ollama-model" and i + 1 < len(args):
            ollama_model = args[i + 1]
            i += 2
        elif a == "--openai" and i + 1 < len(args):
            openai_url = args[i + 1]
            i += 2
        elif a == "--openai-key" and i + 1 < len(args):
            openai_key = args[i + 1]
            i += 2
        elif a == "--openai-model" and i + 1 < len(args):
            openai_model = args[i + 1]
            i += 2
        elif a == "--refine":
            do_refine = True
            i += 1
        elif a in ("--print", "--dry-run"):
            print_only = True
            i += 1
        elif a == "--json":
            json_output = True
            i += 1
        elif a == "--temp" and i + 1 < len(args):
            temperature = float(args[i + 1])
            i += 2
        elif a == "--max-tokens" and i + 1 < len(args):
            max_tokens = int(args[i + 1])
            i += 2
        elif a == "--context" and i + 1 < len(args):
            extra_context = args[i + 1]
            i += 2
        elif a == "--file" and i + 1 < len(args):
            file_input = args[i + 1]
            i += 2
        elif a == "--output" and i + 1 < len(args):
            file_output = args[i + 1]
            i += 2
        elif a == "--":
            # everything after -- is the prompt
            prompt_parts.extend(args[i + 1:])
            break
        else:
            prompt_parts.append(a)
            i += 1

    # --- resolve prompt source (priority: --file > args > stdin) ---
    raw_prompt: str | None = None
    if file_input:
        if file_input == "-":
            raw_prompt = _read_prompt_from_stdin()
        else:
            try:
                with open(file_input, encoding="utf-8") as fh:
                    raw_prompt = fh.read().strip()
            except Exception as e:
                print(f"ERROR reading file {file_input}: {e}", file=sys.stderr)
                sys.exit(1)
    elif prompt_parts:
        raw_prompt = " ".join(prompt_parts)
    else:
        raw_prompt = _read_prompt_from_stdin()

    if not raw_prompt:
        print("ERROR: no prompt provided.", file=sys.stderr)
        sys.exit(1)

    # --- build enriched prompt ---
    task_type = explicit_task if explicit_task else detect_task_type(raw_prompt)
    boosted = build_enriched_prompt(raw_prompt, task_type, extra_context=extra_context, refine=do_refine)

    # --- write output helper ---
    def _write(text: str) -> None:
        if file_output:
            with open(file_output, "w", encoding="utf-8") as fh:
                fh.write(text)
        else:
            print(text)

    # --- dry-run: just print the boosted prompt ---
    if print_only:
        if json_output:
            _write(json.dumps({
                "task_type": detect_task_type(raw_prompt),
                "boosted_prompt": boosted,
                "raw_prompt": raw_prompt,
            }, indent=2))
        else:
            _write(boosted)
        return

    # --- select backend ---
    use_ollama = use_ollama or os.environ.get("DEEPSEEK_USE_OLLAMA", "").lower() in ("1", "true", "yes")
    if use_ollama:
        backend = call_local_ollama
        backend_kw: dict[str, Any] = dict(model=ollama_model, temperature=temperature, max_tokens=max_tokens)
        label = f"Ollama ({ollama_model})"
    elif openai_url:
        key = openai_key or api_key
        if not key:
            print("ERROR: --openai-key required for OpenAI-compatible endpoint", file=sys.stderr)
            sys.exit(1)
        backend = call_openai_compat
        backend_kw = dict(api_key=key, base_url=openai_url, model=openai_model,
                          temperature=temperature, max_tokens=max_tokens)
        label = f"OpenAI-compat ({openai_url}, {openai_model})"
    else:
        backend = call_deepseek_api
        backend_kw = dict(model=model, temperature=temperature, max_tokens=max_tokens)
        label = f"DeepSeek ({model})"

    # --- call ---
    if not json_output and not file_output:
        print(f"\n  Boosting prompt ({task_type}) → sending to {label} ...\n")

    response = backend(boosted, **backend_kw)

    if do_refine and not response.startswith("ERROR"):
        if not json_output and not file_output:
            print("  Refining with second pass ...\n")
        response = refine_answer(raw_prompt, response, backend, **backend_kw)

    if json_output:
        _write(json.dumps({
            "task_type": task_type,
            "boosted_prompt": boosted,
            "model": label,
            "response": response,
        }, indent=2))
    else:
        if file_output:
            _write(response)
        else:
            print("=" * 60)
            print("  RESPONSE")
            print("=" * 60)
            print(response)
            print()


if __name__ == "__main__":
    main()
