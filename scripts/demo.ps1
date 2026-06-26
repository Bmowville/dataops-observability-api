[CmdletBinding()]
param(
    [switch]$StartApi
)

$ErrorActionPreference = "Stop"
$Root = Resolve-Path (Join-Path $PSScriptRoot "..")

Push-Location $Root
try {
    python scripts/demo_setup.py

    if ($StartApi) {
        python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
    }
    else {
        Write-Host ""
        Write-Host "Run with -StartApi to start the local API after seeding."
    }
}
finally {
    Pop-Location
}