# Build Apex-R Android APK (mobile/)
# Prerequisites: Python 3.10+, Java JDK 17, Android SDK (via flet build)
# Run:  .\build_apk.ps1
#
# 手機「直接下載安裝」請看 mobile\PUBLISH.md（Google Drive 直連，私人）
# 建議每 3～4 週更新一次：先改 shared/ 策略邏輯，再執行本腳本或 GitHub Actions。
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

# Windows 主控台預設 cp950，flet/rich 印 emoji 會炸；強制 UTF-8
chcp 65001 > $null
$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"
try {
    [Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
    $OutputEncoding = [System.Text.UTF8Encoding]::new($false)
} catch {}

# Flutter 在沒有 git 時會炸；用已釘住的 engine.version 繞過
$flutterEngineFile = Join-Path $env:USERPROFILE "flutter\3.41.7\bin\internal\engine.version"
if (Test-Path $flutterEngineFile) {
    $env:FLUTTER_PREBUILT_ENGINE_VERSION = (Get-Content $flutterEngineFile -Raw).Trim()
    Write-Host "FLUTTER_PREBUILT_ENGINE_VERSION=$($env:FLUTTER_PREBUILT_ENGINE_VERSION)"
}

# Ensure JDK 17 is on PATH if installed via winget
if (-not $env:JAVA_HOME -or -not (Test-Path "$env:JAVA_HOME\bin\java.exe")) {
    $jdk = Get-ChildItem "C:\Program Files\Eclipse Adoptium" -Directory -ErrorAction SilentlyContinue |
        Where-Object { $_.Name -like "jdk-17*" } | Select-Object -First 1
    if ($jdk) {
        $env:JAVA_HOME = $jdk.FullName
        $env:Path = "$env:JAVA_HOME\bin;" + $env:Path
    }
}

# Flutter / flet need ANDROID_HOME
$androidSdk = Join-Path $env:USERPROFILE "Android\Sdk"
if (Test-Path $androidSdk) {
    $env:ANDROID_HOME = $androidSdk
    $env:ANDROID_SDK_ROOT = $androidSdk
    $env:Path = "$androidSdk\platform-tools;$androidSdk\cmdline-tools\latest\bin;" + $env:Path
    Write-Host "ANDROID_HOME=$env:ANDROID_HOME"
} else {
    Write-Host "WARNING: Android SDK not found at $androidSdk"
}

$Root = Split-Path $PSScriptRoot -Parent
& (Join-Path $Root "sync_shared.ps1")

$versionFile = Join-Path $PSScriptRoot "VERSION"
if (-not (Test-Path $versionFile)) {
    "2.1.0" | Set-Content $versionFile -Encoding utf8
}
$version = (Get-Content $versionFile -Raw).Trim()
$buildNumber = ($version -replace '[^\d]', '')
if (-not $buildNumber) { $buildNumber = "1" }
Write-Host "Building Apex-R mobile APK v$version (build $buildNumber) ..."

Write-Host "Installing mobile dependencies..."
py -3.13 -m pip install -r requirements.txt -q
py -3.13 -m pip install "flet[all]" -q

$pyScripts = (py -3.13 -c "import sysconfig; print(sysconfig.get_path('scripts'))").Trim()
$fletExe = Join-Path $pyScripts "flet.exe"
if (-not (Test-Path $fletExe)) {
    throw "找不到 flet.exe（$fletExe）。請執行: py -3.13 -m pip install `"flet[all]`""
}
$env:Path = "$pyScripts;" + $env:Path

# Bundle shared + mobile code for Flet (fresh dir — avoid locked gradle files under old build_bundle)
$bundleDir = Join-Path $PSScriptRoot "build_bundle"
$stamp = Get-Date -Format "yyyyMMddHHmmss"
$freshBundle = Join-Path $PSScriptRoot ("build_bundle_" + $stamp)
New-Item -ItemType Directory -Force -Path $freshBundle | Out-Null
Copy-Item -Force main.py, bootstrap.py, config.yaml, VERSION, requirements.txt $freshBundle
Copy-Item -Recurse -Force (Join-Path $PSScriptRoot "lib") (Join-Path $freshBundle "lib")
# Prefer renaming aside; if locked, keep old tree and build from fresh path
if (Test-Path $bundleDir) {
    $aside = Join-Path $PSScriptRoot ("build_bundle_old_" + $stamp)
    try {
        Move-Item -Force $bundleDir $aside -ErrorAction Stop
        Write-Host "Moved previous build_bundle -> $aside"
    } catch {
        Write-Host "WARNING: could not move old build_bundle (locked). Building in $freshBundle"
    }
}
if (-not (Test-Path $bundleDir)) {
    Move-Item -Force $freshBundle $bundleDir
} else {
    $bundleDir = $freshBundle
}
Write-Host "Using bundle dir: $bundleDir"

# Preflight: desktop smoke (imports + tiny yfinance/monitor) before long APK build
Write-Host "Running mobile smoke test..."
Push-Location $PSScriptRoot
try {
    py -3.13 smoke_test_mobile.py
    if ($LASTEXITCODE -ne 0) { throw "smoke_test_mobile.py failed — aborting APK build" }
} finally {
    Pop-Location
}

$logFile = Join-Path $PSScriptRoot "build_apk.log"
Push-Location $bundleDir
try {
    Write-Host "Running: flet build apk ..."
    Write-Host "（首次需下載 Flutter/Android 工具，可能較久）"
    Write-Host "log: $logFile"
    # INTERNET for yfinance; disable Impeller (Xiaomi/Mali black screen); white splash
    & $fletExe build apk `
        --project "Apex-R" `
        --build-version $version `
        --build-number $buildNumber `
        --org "com.example.apexr" `
        --product "Apex-R" `
        --android-permissions "android.permission.INTERNET=true" `
        --android-meta-data "io.flutter.embedding.android.EnableImpeller=false" `
        --splash-color "#FFFFFF" `
        --splash-dark-color "#FFFFFF" `
        --clear-cache `
        --yes `
        --no-rich-output `
        *> $logFile
    if ($LASTEXITCODE -ne 0) {
        Get-Content $logFile -Tail 80 -ErrorAction SilentlyContinue
        throw "flet build apk failed (exit $LASTEXITCODE). See $logFile"
    }
    $apkDir = Join-Path $bundleDir "build\apk"
    if (-not (Test-Path $apkDir)) {
        # newer flet may put apk under build/
        $apkDir = Join-Path $bundleDir "build"
    }
    $found = Get-ChildItem $apkDir -Filter "*.apk" -Recurse -ErrorAction SilentlyContinue | Select-Object -First 1
    if (-not $found) {
        Get-Content $logFile -Tail 80 -ErrorAction SilentlyContinue
        throw "APK not found under $apkDir. See $logFile"
    }
    $outApk = Join-Path $PSScriptRoot ("dist\Apex-R-v{0}.apk" -f $version)
    New-Item -ItemType Directory -Force -Path (Join-Path $PSScriptRoot "dist") | Out-Null
    Copy-Item -Force $found.FullName $outApk
    Write-Host "APK: $outApk"

    Write-Host "Verifying APK embeds numpy/pandas/yfinance..."
    & (Join-Path $PSScriptRoot "verify_apk_deps.ps1") -ApkPath $outApk
} finally {
    Pop-Location
}

Write-Host ""
Write-Host "若 flet build 失敗，可先本機預覽:  py -3.13 main.py"
Write-Host "下一版請更新 mobile/VERSION 後再執行 build_apk.ps1"
