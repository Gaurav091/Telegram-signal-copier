<#
.SYNOPSIS
    One-click setup for the DeepSeek Prompt Booster (Windows).
.DESCRIPTION
    - Installs Python dependencies (requests)
    - Prompts for DeepSeek API key (optional)
    - Adds 'ask' function permanently to PowerShell profile
    - Validates the environment
    - Tests the booster
.NOTES
    Run from PowerShell as:  .\tools\setup.ps1
    Or double-click (if execution policy allows).
#>

$ErrorActionPreference = "Stop"
$Host.UI.RawUI.WindowTitle = "Prompt Booster — Setup"

$ProjectRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$VenvPython = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
$BoosterScript = Join-Path $ProjectRoot "tools\deepseek_booster.py"
$EnvFile = Join-Path $ProjectRoot ".env"

Write-Host "╔══════════════════════════════════════════════════════╗" -ForegroundColor Cyan
Write-Host "║       Prompt Booster — Windows Setup                ║" -ForegroundColor Cyan
Write-Host "╚══════════════════════════════════════════════════════╝" -ForegroundColor Cyan
Write-Host ""

# ---------------------------------------------------------------
# Step 1 — Detect Python
# ---------------------------------------------------------------
Write-Host "▶ Step 1/5 — Detecting Python..." -ForegroundColor Yellow

if (-not (Test-Path $VenvPython)) {
    Write-Host "  Virtual env python not found at $VenvPython" -ForegroundColor Red
    Write-Host "  Please create the venv first:"
    Write-Host "    python -m venv .venv"
    Write-Host "    &.venv\Scripts\Activate.ps1"
    Write-Host "    pip install -r requirements.txt"
    exit 1
}
Write-Host "  Found: $VenvPython" -ForegroundColor Green
$PyVersion = & $VenvPython --version
Write-Host "  $PyVersion" -ForegroundColor Gray

# ---------------------------------------------------------------
# Step 2 — Install dependencies
# ---------------------------------------------------------------
Write-Host ""
Write-Host "▶ Step 2/5 — Installing dependencies..." -ForegroundColor Yellow
& $VenvPython -m pip install requests -q
if ($LASTEXITCODE -ne 0) {
    Write-Host "  Failed to install requests. Try manually: pip install requests" -ForegroundColor Red
    exit 1
}
Write-Host "  requests: OK" -ForegroundColor Green

# ---------------------------------------------------------------
# Step 3 — API key prompt
# ---------------------------------------------------------------
Write-Host ""
Write-Host "▶ Step 3/5 — DeepSeek API key (optional)..." -ForegroundColor Yellow

$CurrentKey = ""
if (Test-Path $EnvFile) {
    $envContent = Get-Content $EnvFile -Raw -ErrorAction SilentlyContinue
    if ($envContent -match 'DEEPSEEK_API_KEY=(.+)') {
        $CurrentKey = $matches[1].Trim().Trim('"').Trim("'")
    }
}

if ($CurrentKey) {
    Write-Host "  Existing key found in .env: ${CurrentKey}..." -ForegroundColor Green
    $change = Read-Host "  Change it? (y/N)"
    if ($change -eq "y") {
        $NewKey = Read-Host "  Enter your DeepSeek API key (or leave blank to skip)"
        if ($NewKey) {
            $CurrentKey = $NewKey
            # Update .env
            if (Test-Path $EnvFile) {
                $content = Get-Content $EnvFile -Raw
                if ($content -match 'DEEPSEEK_API_KEY=') {
                    $content = $content -replace 'DEEPSEEK_API_KEY=.*', "DEEPSEEK_API_KEY=$CurrentKey"
                } else {
                    $content += "`nDEEPSEEK_API_KEY=$CurrentKey"
                }
                Set-Content $EnvFile -Value $content
            }
            Write-Host "  .env updated." -ForegroundColor Green
        }
    }
} else {
    $NewKey = Read-Host "  Enter DeepSeek API key (or press Enter to skip)"
    if ($NewKey) {
        # Add to .env
        Add-Content $EnvFile -Value "`nDEEPSEEK_API_KEY=$NewKey" -ErrorAction SilentlyContinue
        Write-Host "  Added DEEPSEEK_API_KEY to .env" -ForegroundColor Green
    } else {
        Write-Host "  Skipped. Use --print mode to get boosted prompts without an API key." -ForegroundColor Yellow
    }
}

# ---------------------------------------------------------------
# Step 4 — Install 'ask' function permanently
# ---------------------------------------------------------------
Write-Host ""
Write-Host "▶ Step 4/5 — Installing 'ask' command..." -ForegroundColor Yellow

$ProfilePath = $PROFILE.CurrentUserAllHosts
$ProfileDir = Split-Path -Parent $ProfilePath
if (-not (Test-Path $ProfileDir)) {
    New-Item -ItemType Directory -Path $ProfileDir -Force | Out-Null
}

$AskFunction = @"

# ----- DeepSeek Prompt Booster -----
function ask {
    <#
    .SYNOPSIS
        Auto-boost a prompt and send to DeepSeek Flash (or just print the boosted text).
    .EXAMPLE
        ask "Explain quantum computing"
        ask --refine "Compare Python and Java"
        ask --print "write a poem"
        echo "Is solar worth it?" | ask
        ask --task DECISION "Should I buy solar panels?"
    #>
    & "$VenvPython" "$BoosterScript" @args
}
# ------------------------------------
"@

# Check if already installed
$ProfileContent = ""
if (Test-Path $ProfilePath) {
    $ProfileContent = Get-Content $ProfilePath -Raw -ErrorAction SilentlyContinue
}

if ($ProfileContent -and $ProfileContent.Contains("function ask")) {
    Write-Host "  'ask' function already exists in profile." -ForegroundColor Green
} else {
    Add-Content $ProfilePath -Value $AskFunction
    Write-Host "  Added 'ask' function to: $ProfilePath" -ForegroundColor Green
    Write-Host "  Restart your terminal or run: . $ProfilePath" -ForegroundColor Yellow
}

# Also register ask.cmd in PATH (optional)
$AskCmd = Join-Path $ProjectRoot "tools\ask.cmd"
if (Test-Path $AskCmd) {
    Write-Host "  Also available as: $AskCmd" -ForegroundColor Gray
    Write-Host "  Add tools\ directory to your PATH to use 'ask' from any CMD." -ForegroundColor Gray
}

# ---------------------------------------------------------------
# Step 5 — Validate
# ---------------------------------------------------------------
Write-Host ""
Write-Host "▶ Step 5/5 — Validating..." -ForegroundColor Yellow

# Test --print mode (no API key needed)
$testResult = & $VenvPython $BoosterScript --print -- "test validation" 2>&1
if ($LASTEXITCODE -eq 0 -and $testResult) {
    Write-Host "  --print mode: OK" -ForegroundColor Green
} else {
    Write-Host "  --print mode: FAILED" -ForegroundColor Red
    Write-Host "  $testResult"
}

# Test task type detection
$detectResult = & $VenvPython -c "
import sys; sys.path.insert(0, r'$ProjectRoot\tools')
from deepseek_booster import detect_task_type
tests = [('compare Go vs Rust','ANALYSIS'),('implement a function','CODE'),('should I buy this','DECISION'),('how to install','INSTRUCTION'),('what is gravity','FACTUAL'),('write a story','CREATIVE')]
ok = all(detect_task_type(p)==e for p,e in tests)
print('OK' if ok else 'FAIL')
" 2>&1
if ($detectResult -match "OK") {
    Write-Host "  Task detection: OK" -ForegroundColor Green
} else {
    Write-Host "  Task detection: FAILED" -ForegroundColor Red
    Write-Host "  $detectResult"
}

# Test Python import
$importResult = & $VenvPython -c "
from tools.deepseek_booster import build_enriched_prompt, boost_prompt, detect_task_type, format_spec_for
enriched = build_enriched_prompt('test', 'GENERAL')
assert '<thinking>' in enriched
assert 'test' in enriched
print('Import + build_enriched_prompt: OK')
" 2>&1
if ($importResult -match "OK") {
    Write-Host "  Python library import: OK" -ForegroundColor Green
} else {
    Write-Host "  Python library import: FAILED" -ForegroundColor Red
    Write-Host "  $importResult"
}

# Check API key
if ($CurrentKey -or $NewKey) {
    Write-Host "  DeepSeek API key: configured" -ForegroundColor Green
} else {
    Write-Host "  DeepSeek API key: not set (use --print mode or ask --print)" -ForegroundColor Yellow
}

# ---------------------------------------------------------------
# Done
# ---------------------------------------------------------------
Write-Host ""
Write-Host "╔══════════════════════════════════════════════════════╗" -ForegroundColor Cyan
Write-Host "║                    SETUP COMPLETE                    ║" -ForegroundColor Cyan
Write-Host "╚══════════════════════════════════════════════════════╝" -ForegroundColor Cyan
Write-Host ""
Write-Host "  Usage:" -ForegroundColor White
Write-Host ""
Write-Host "    ask "Explain quantum computing"" -ForegroundColor Magenta
Write-Host "    ask --refine "Compare Python and Java"" -ForegroundColor Magenta
Write-Host "    ask --print "analyse project for gaps"" -ForegroundColor Magenta
Write-Host "    ask --task DECISION "Should I buy solar panels?"" -ForegroundColor Magenta
Write-Host "    echo "Is solar worth it?" | ask" -ForegroundColor Magenta
Write-Host "    ask --file prompt.txt --output result.txt" -ForegroundColor Magenta
Write-Host ""
Write-Host "  No API key? Use --print to get the boosted text for copy-paste:" -ForegroundColor Yellow
Write-Host "    ask --print "your question here"" -ForegroundColor Magenta
Write-Host ""
Write-Host "  Need to restart your terminal or run:" -ForegroundColor Gray
Write-Host "    . $ProfilePath" -ForegroundColor Gray
