Param(
    [string[]]$Patterns = @()
)
$path = 'C:\Users\HP\AppData\Roaming\MetaQuotes\Terminal\Common\Files\TelegramSignalCopierBridge\outbox'
Get-ChildItem -Path $path -Filter '*.result' | ForEach-Object {
    $file = $_.FullName
    try {
        $content = Get-Content $file -Raw -ErrorAction Stop
    } catch {
        return
    }
    foreach ($p in $Patterns) {
        if ($content -match [regex]::Escape($p)) {
            $matches = Select-String -Path $file -Pattern $p -AllMatches
            foreach ($m in $matches) {
                Write-Output ("$($file):$($m.Line)")
            }
            break
        }
    }
}
