param(
    [switch]$InstallWakeWord
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
$defaultModelPath = Join-Path $repoRoot "data\vosk\vosk-model-small-ru-0.22"

Push-Location $repoRoot
try {
    $modelPath = python -c "from modules.input_hub.wake_word import discover_vosk_model_path; p=discover_vosk_model_path(); print(p or '')"
} finally {
    Pop-Location
}
$modelPath = "$modelPath".Trim()

if ($InstallWakeWord -and -not $modelPath) {
    Push-Location $repoRoot
    try {
        python -m vosk_install
    } finally {
        Pop-Location
    }
    if (Test-Path -LiteralPath $defaultModelPath -PathType Container) {
        $modelPath = $defaultModelPath
    }
}

if ($modelPath -and (Test-Path -LiteralPath $modelPath -PathType Container)) {
    $env:NOVA_WAKE_WORD_ENABLED = "true"
    $env:NOVA_VOSK_MODEL = $modelPath
    Write-Host "Wake word: enabled ($modelPath)" -ForegroundColor Green
} else {
    Write-Warning "Vosk model is missing. Run .\scripts\dev-desktop.ps1 -InstallWakeWord"
}

Push-Location (Join-Path $repoRoot "apps\desktop")
try {
    npm run tauri dev
} finally {
    Pop-Location
}
