# Build Apex-R 4.0 standalone Windows exe (desktop/)
# Run in PowerShell:  .\build_exe.ps1
# (GitHub Actions builds the same thing: .github/workflows/build-exe.yml)

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

Write-Host "Apex-R 4.0 - building standalone exe..."
py -3 -m pip install -r requirements.txt pyinstaller curl_cffi -q

# Do NOT use --clean: it fails if Apex-R-4.0.exe is still running.
py -3 -m PyInstaller --noconfirm --distpath "dist" --workpath "build" Apex-R.spec

$outDir = Join-Path $PSScriptRoot "dist\Apex-R-4.0"
Copy-Item -Force config.yaml (Join-Path $outDir "config.yaml")
Copy-Item -Force config_apex_m.yaml (Join-Path $outDir "config_apex_m.yaml")

Write-Host ""
Write-Host "Done!  Double-click: desktop\dist\Apex-R-4.0\Apex-R-4.0.exe"
Write-Host "Close any running Apex-R before rebuilding."
