# Verify packaged APK contains required Python modules (numpy/pandas/yfinance).
param(
    [Parameter(Mandatory = $true)][string]$ApkPath
)
$ErrorActionPreference = "Stop"
if (-not (Test-Path $ApkPath)) { throw "APK not found: $ApkPath" }

$tmp = Join-Path $env:TEMP ("apex-apk-check-" + [guid]::NewGuid().ToString("n"))
New-Item -ItemType Directory -Force -Path $tmp | Out-Null
try {
    Copy-Item -Force $ApkPath (Join-Path $tmp "app.apk")
    Push-Location $tmp
    try {
        Rename-Item app.apk app.zip
        Expand-Archive -Force app.zip -DestinationPath extracted
    } finally {
        Pop-Location
    }

    $needles = @("numpy", "pandas", "yfinance", "yaml", "pytz")
    $hits = @{}
    foreach ($n in $needles) { $hits[$n] = $false }

    $files = Get-ChildItem (Join-Path $tmp "extracted") -Recurse -File -ErrorAction SilentlyContinue
    foreach ($f in $files) {
        $name = $f.Name.ToLowerInvariant()
        $rel = $f.FullName.Substring($tmp.Length).ToLowerInvariant()
        foreach ($n in $needles) {
            if ($name -like "*$n*" -or $rel -like "*\$n\*" -or $rel -like "*/$n/*") {
                $hits[$n] = $true
            }
        }
        # site-packages often live inside .so / zip payloads — scan small text/zip names
        if ($name -match "sitepackages|pythonsite|python-stdlib|app\.zip") {
            Write-Host "payload: $($f.FullName.Substring($tmp.Length)) size=$($f.Length)"
        }
    }

    # Also strings-scan the largest site-packages .so / zip for module names
    $payloads = $files | Where-Object {
        $_.Name -match "sitepackages|pythonsite" -or ($_.Extension -eq ".zip" -and $_.Length -gt 100KB)
    } | Sort-Object Length -Descending | Select-Object -First 5

    foreach ($p in $payloads) {
        Write-Host "scanning $($p.Name) ($([math]::Round($p.Length/1MB,1)) MB) ..."
        $bytes = [System.IO.File]::ReadAllBytes($p.FullName)
        $text = [System.Text.Encoding]::ASCII.GetString($bytes)
        foreach ($n in $needles) {
            if ($text.Contains($n)) { $hits[$n] = $true }
        }
    }

    $failed = @()
    foreach ($n in $needles) {
        if ($hits[$n]) { Write-Host "FOUND $n" } else { Write-Host "MISSING $n"; $failed += $n }
    }
    if ($failed.Count -gt 0) {
        throw ("APK missing modules: " + ($failed -join ", "))
    }
    Write-Host "APK dependency check PASSED: $ApkPath"
} finally {
    Remove-Item -Recurse -Force $tmp -ErrorAction SilentlyContinue
}
