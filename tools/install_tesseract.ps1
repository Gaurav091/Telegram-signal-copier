Set-StrictMode -Version Latest
Write-Output '---BEGIN TESSERACT INSTALL SCRIPT---'

if (Get-Command tesseract -ErrorAction SilentlyContinue) {
    Write-Output 'TESSERACT_ALREADY_PRESENT'
    tesseract --version
    exit 0
}

# Try winget if available
if (Get-Command winget -ErrorAction SilentlyContinue) {
    Write-Output 'WINGET_AVAILABLE'
    try {
        winget install --id UB-Mannheim.Tesseract -e --silent --accept-package-agreements --accept-source-agreements | Out-Null
        Start-Sleep -Seconds 2
        if (Get-Command tesseract -ErrorAction SilentlyContinue) {
            Write-Output 'TESSERACT_INSTALLED_VIA_WINGET'
            tesseract --version
            exit 0
        } else {
            Write-Output 'WINGET_INSTALL_ATTEMPTED_BUT_NOT_FOUND'
        }
    } catch {
        Write-Output "WINGET_ERROR: $_"
    }
} else {
    Write-Output 'WINGET_NOT_AVAILABLE'
}

# Try Chocolatey install
if (-not (Get-Command choco -ErrorAction SilentlyContinue)) {
    Write-Output 'CHOCOLATEY_NOT_FOUND_ATTEMPTING_INSTALL'
    try {
        Set-ExecutionPolicy Bypass -Scope Process -Force
        [System.Net.ServicePointManager]::SecurityProtocol = [System.Net.SecurityProtocolType]::Tls12
        iex ((New-Object System.Net.WebClient).DownloadString('https://community.chocolatey.org/install.ps1'))
        Start-Sleep -Seconds 5
    } catch {
        Write-Output "CHOCOLATEY_INSTALL_ERROR: $_"
    }
}

if (Get-Command choco -ErrorAction SilentlyContinue) {
    Write-Output 'CHOCOLATEY_AVAILABLE'
    try {
        choco install tesseract -y --no-progress | Out-Null
        Start-Sleep -Seconds 2
        if (Get-Command tesseract -ErrorAction SilentlyContinue) {
            Write-Output 'TESSERACT_INSTALLED_VIA_CHOCOLATEY'
            tesseract --version
            exit 0
        } else {
            Write-Output 'CHOCOLATEY_INSTALL_ATTEMPTED_BUT_NOT_FOUND'
        }
    } catch {
        Write-Output "CHOCOLATEY_INSTALL_ERROR: $_"
    }
} else {
    Write-Output 'CHOCOLATEY_UNAVAILABLE_AFTER_ATTEMPT'
}

Write-Output 'TESSERACT_INSTALL_FAILED'
exit 1
