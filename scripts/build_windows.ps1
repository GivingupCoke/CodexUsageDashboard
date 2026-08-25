[CmdletBinding()]
param(
    [switch]$SkipTests
)

$ErrorActionPreference = "Stop"
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path

Push-Location $projectRoot
try {
    python -m PyInstaller --version | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw 'PyInstaller is not installed. Run: python -m pip install -e ".[build]"'
    }

    if (-not $SkipTests) {
        $env:PYTEST_DISABLE_PLUGIN_AUTOLOAD = "1"
        python -m pytest -q
        if ($LASTEXITCODE -ne 0) {
            throw "Tests failed; the Windows executable was not built."
        }
    }

    python -m PyInstaller `
        --noconfirm `
        --clean `
        --onefile `
        --windowed `
        --name CodexUsageDashboard `
        --icon (Join-Path $projectRoot "assets\codex_usage_dashboard.ico") `
        --add-data "$(Join-Path $projectRoot 'assets');assets" `
        --distpath dist `
        --workpath build/pyinstaller `
        --specpath build `
        codex_usage_dashboard.py
    if ($LASTEXITCODE -ne 0) {
        throw "PyInstaller failed."
    }

    $executable = Join-Path $projectRoot "dist\CodexUsageDashboard.exe"
    if (-not (Test-Path -LiteralPath $executable)) {
        throw "Build completed without producing $executable"
    }

    Write-Host "Windows executable created: $executable"
}
finally {
    Pop-Location
}
