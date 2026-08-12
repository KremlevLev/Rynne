$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
$python = (py -3 -c "import sys; print(sys.executable)").Trim()
if (-not $python -or -not (Test-Path -LiteralPath $python -PathType Leaf)) {
    throw "A real Python installation was not found."
}
$pythonw = Join-Path (Split-Path -Parent $python) "pythonw.exe"
if (-not (Test-Path -LiteralPath $pythonw -PathType Leaf)) {
    throw "pythonw.exe was not found next to $python"
}
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
# Stop old bridge instances so an updated script takes effect immediately.
Get-CimInstance Win32_Process -Filter "Name = 'pythonw.exe'" -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -like '*rynne_wake_bridge.py*' } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
Start-Process -FilePath $pythonw -ArgumentList ('"' + $script + '"') -WorkingDirectory $repoRoot -WindowStyle Hidden
Write-Host "Rynne Wake Bridge installed and started." -ForegroundColor Green
Write-Host $shortcutPath
