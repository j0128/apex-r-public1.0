# Sync shared/ core modules to colab/modules and mobile/lib
# Run from project root:  .\sync_shared.ps1

$ErrorActionPreference = "Stop"
$Root = $PSScriptRoot
$Shared = Join-Path $Root "shared"
$Targets = @(
    (Join-Path $Root "colab\modules"),
    (Join-Path $Root "mobile\lib")
)

$Files = @("apex_core.py", "universe_builder.py", "strategy_presets.py", "config_io.py", "committee.py", "committee_tw.py", "allocation_sheet.py", "markets.py")

foreach ($target in $Targets) {
    New-Item -ItemType Directory -Force -Path $target | Out-Null
    foreach ($name in $Files) {
        Copy-Item -Force (Join-Path $Shared $name) (Join-Path $target $name)
    }
    Write-Host "Synced -> $target"
}

Write-Host "Done."
