# Copy shared modules into colab/modules (for notebook upload)
$ErrorActionPreference = "Stop"
$Root = Split-Path $PSScriptRoot -Parent
& (Join-Path $Root "sync_shared.ps1")
