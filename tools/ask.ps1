#!/usr/bin/env pwsh
<#
.SYNOPSIS
    Auto-boost any prompt and send to DeepSeek Flash (or Ollama / any OpenAI-compatible endpoint).
.DESCRIPTION
    Wraps tools/deepseek_booster.py for convenient PowerShell usage.
    Usage: ask "what is quantum computing?"
           ask --ollama "compare Go vs Rust"
           ask --help
.EXAMPLE
    ask "explain monads"
    ask --refine "write a haiku about TCP/IP"
    ask --openai https://api.groq.com --openai-key gsk_... --openai-model llama-3.3-70b "FFT explained"
#>

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectDir = Split-Path -Parent $ScriptDir
$VenvPython = Join-Path $ProjectDir ".venv\Scripts\python.exe"

if (-not (Test-Path $VenvPython)) {
    Write-Error "Virtual environment python not found at $VenvPython"
    exit 1
}

& $VenvPython (Join-Path $ScriptDir "deepseek_booster.py") @args
