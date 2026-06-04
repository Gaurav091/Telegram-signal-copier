param(
    [switch]$Clean,
    [switch]$SkipInstaller,
    [string]$PythonExe = ""
)

$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $RepoRoot

if (-not $PythonExe) {
    $VenvPython = Join-Path $RepoRoot ".venv\Scripts\python.exe"
    if (Test-Path $VenvPython) {
        $PythonExe = $VenvPython
    }
    else {
        $PythonExe = "python"
    }
}

function Invoke-Python {
    param(
        [Parameter(Mandatory = $true)]
        [string[]]$Arguments
    )

    & $PythonExe @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Python command failed: $PythonExe $($Arguments -join ' ')"
    }
}

function Get-ProjectVersion {
    $pyproject = Join-Path $RepoRoot "pyproject.toml"
    $match = Select-String -Path $pyproject -Pattern '^version\s*=\s*"([^"]+)"' | Select-Object -First 1
    if ($match -and $match.Matches.Count -gt 0) {
        return $match.Matches[0].Groups[1].Value
    }
    return "0.1.0"
}

function Find-Iscc {
    $candidates = @(
        (Join-Path ${env:ProgramFiles(x86)} "Inno Setup 6\ISCC.exe"),
        (Join-Path $env:ProgramFiles "Inno Setup 6\ISCC.exe"),
        (Join-Path $env:LOCALAPPDATA "Programs\Inno Setup 6\ISCC.exe"),
        (Join-Path $env:APPDATA "Programs\Inno Setup 6\ISCC.exe")
    ) | Where-Object { $_ }

    foreach ($candidate in $candidates) {
        if (Test-Path $candidate) {
            return $candidate
        }
    }

    return $null
}

if ($Clean) {
    Write-Host "Stopping any running instances of TelegramSignalCopier or Python in this project to clear file locks..."
    Get-Process -Name TelegramSignalCopier -ErrorAction SilentlyContinue | Stop-Process -Force
    Get-Process -Name python -ErrorAction SilentlyContinue | Where-Object {
        try { $_.Path -like "*Telegram signal Copier*" } catch { $false }
    } | Stop-Process -Force
    Start-Sleep -Seconds 1 # Allow file system handles to close

    Remove-Item (Join-Path $RepoRoot "build") -Recurse -Force -ErrorAction SilentlyContinue
    Remove-Item (Join-Path $RepoRoot "dist") -Recurse -Force -ErrorAction SilentlyContinue
}

Write-Host "Using Python:" $PythonExe
Invoke-Python -Arguments @("-m", "pip", "install", "--upgrade", "pip")
Invoke-Python -Arguments @("-m", "pip", "install", "-r", "requirements.txt")
Invoke-Python -Arguments @("-m", "pip", "install", "-e", ".[telegram,build]")
Invoke-Python -Arguments @("-m", "PyInstaller", "--noconfirm", "--clean", "packaging\TelegramSignalCopier.spec")

$bundlePath = Join-Path $RepoRoot "dist\TelegramSignalCopier\TelegramSignalCopier.exe"
if (-not (Test-Path $bundlePath)) {
    throw "Build finished without bundle: $bundlePath"
}

Write-Host "App bundle ready:" $bundlePath

if (-not $SkipInstaller) {
    $iscc = Find-Iscc
    if ($iscc) {
        $version = Get-ProjectVersion
        & $iscc "/DAppVersion=$version" "packaging\TelegramSignalCopier.iss"
        if ($LASTEXITCODE -ne 0) {
            throw "Inno Setup compilation failed"
        }
        Write-Host "Installer ready under dist\installer"
    }
    else {
        Write-Warning "Inno Setup 6 not found. App bundle built, installer skipped."
    }
}