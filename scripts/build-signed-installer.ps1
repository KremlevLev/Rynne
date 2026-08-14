$ErrorActionPreference = "Stop"

$repositoryRoot = Split-Path -Parent $PSScriptRoot
$desktopRoot = Join-Path $repositoryRoot "apps\desktop"
$signingRoot = Join-Path $env:USERPROFILE ".rynne\signing"
$privateKeyPath = Join-Path $signingRoot "rynne-updater.key"
$passwordPath = Join-Path $signingRoot "rynne-updater.password"

if (-not (Test-Path -LiteralPath $privateKeyPath -PathType Leaf)) {
    throw "Updater private key is missing: $privateKeyPath"
}
if (-not (Test-Path -LiteralPath $passwordPath -PathType Leaf)) {
    throw "Updater key password is missing: $passwordPath"
}

$locationPushed = $false
try {
    $env:TAURI_SIGNING_PRIVATE_KEY = (
        Get-Content -LiteralPath $privateKeyPath -Raw
    ).Trim()
    $env:TAURI_SIGNING_PRIVATE_KEY_PASSWORD = (
        Get-Content -LiteralPath $passwordPath -Raw
    ).Trim()

    Push-Location $desktopRoot
    $locationPushed = $true
    npm run installer
    if ($LASTEXITCODE -ne 0) {
        throw "Signed installer build failed with exit code $LASTEXITCODE."
    }

    $bundleRoot = Join-Path $desktopRoot "src-tauri\target\release\bundle\nsis"
    $installer = Get-ChildItem -LiteralPath $bundleRoot -Filter "Rynne_*_x64-setup.exe" |
        Sort-Object LastWriteTime -Descending |
        Select-Object -First 1
    if ($null -eq $installer) {
        throw "The signed NSIS installer was not produced."
    }
    $signaturePath = "$($installer.FullName).sig"
    if (-not (Test-Path -LiteralPath $signaturePath -PathType Leaf)) {
        throw "The updater signature was not produced: $signaturePath"
    }

    $hash = (Get-FileHash -LiteralPath $installer.FullName -Algorithm SHA256).Hash
    $checksumPath = "$($installer.FullName).sha256"
    "$hash  $($installer.Name)" | Set-Content -LiteralPath $checksumPath -Encoding ascii

    Write-Host "Signed installer: $($installer.FullName)"
    Write-Host "Updater signature: $signaturePath"
    Write-Host "SHA-256: $hash"
}
finally {
    if ($locationPushed) {
        Pop-Location
    }
    Remove-Item Env:TAURI_SIGNING_PRIVATE_KEY -ErrorAction SilentlyContinue
    Remove-Item Env:TAURI_SIGNING_PRIVATE_KEY_PASSWORD -ErrorAction SilentlyContinue
}
