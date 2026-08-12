param(
    [string]$OutputDirectory = (Join-Path ([Environment]::GetFolderPath("Desktop")) "Rynne diagnostics")
)

$ErrorActionPreference = "Stop"
$timestamp = Get-Date -Format "yyyy-MM-dd_HH-mm-ss"
$bundleRoot = Join-Path $OutputDirectory "rynne-diagnostics-$timestamp"
$logsTarget = Join-Path $bundleRoot "logs"
$appLogs = Join-Path $env:LOCALAPPDATA "ai.nova.desktop\logs"

New-Item -ItemType Directory -Force -Path $logsTarget | Out-Null

if (Test-Path -LiteralPath $appLogs -PathType Container) {
    Get-ChildItem -LiteralPath $appLogs -File -Recurse |
        Where-Object { $_.Length -le 50MB } |
        ForEach-Object {
            $relative = $_.FullName.Substring($appLogs.Length).TrimStart('\')
            $destination = Join-Path $logsTarget $relative
            New-Item -ItemType Directory -Force -Path (Split-Path -Parent $destination) | Out-Null
            Copy-Item -LiteralPath $_.FullName -Destination $destination
        }
}

$systemInfo = @(
    "Rynne diagnostics"
    "Collected: $(Get-Date -Format o)"
    "Windows: $([Environment]::OSVersion.VersionString)"
    "PowerShell: $($PSVersionTable.PSVersion)"
    "Computer: $env:COMPUTERNAME"
    "User: $env:USERNAME"
    "Log source: $appLogs"
    ""
    "Rynne processes:"
    (Get-Process -ErrorAction SilentlyContinue |
        Where-Object { $_.ProcessName -match 'rynne|nova' } |
        Select-Object ProcessName, Id, CPU, WorkingSet64, StartTime |
        Format-Table -AutoSize | Out-String)
)
$systemInfo | Set-Content -LiteralPath (Join-Path $bundleRoot "system.txt") -Encoding utf8

$zipPath = "$bundleRoot.zip"
Compress-Archive -LiteralPath $bundleRoot -DestinationPath $zipPath -Force
Remove-Item -LiteralPath $bundleRoot -Recurse -Force

Write-Host "Diagnostic bundle created:" -ForegroundColor Green
Write-Host $zipPath
Write-Host "Secrets and .env files were not included." -ForegroundColor DarkGray
