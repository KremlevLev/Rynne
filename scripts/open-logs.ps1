$logDirectory = Join-Path $env:LOCALAPPDATA "ai.nova.desktop\logs"

if (-not (Test-Path -LiteralPath $logDirectory -PathType Container)) {
    New-Item -ItemType Directory -Force -Path $logDirectory | Out-Null
}

Start-Process explorer.exe -ArgumentList $logDirectory
