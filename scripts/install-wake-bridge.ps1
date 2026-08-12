$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
$pythonw = (Get-Command pythonw.exe -ErrorAction Stop).Source
$script = Join-Path $PSScriptRoot "rynne_wake_bridge.py"
$startup = [Environment]::GetFolderPath("Startup")
$shortcutPath = Join-Path $startup "Rynne Wake Bridge.lnk"
$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut($shortcutPath)
$shortcut.TargetPath = $pythonw
$shortcut.Arguments = '"' + $script + '"'
$shortcut.WorkingDirectory = $repoRoot
$shortcut.WindowStyle = 7
$shortcut.Description = "Starts Rynne after a secure Telegram Mini App wake request"
$shortcut.Save()
Start-Process -FilePath $pythonw -ArgumentList ('"' + $script + '"') -WorkingDirectory $repoRoot -WindowStyle Hidden
Write-Host "Rynne Wake Bridge installed and started." -ForegroundColor Green
Write-Host $shortcutPath
