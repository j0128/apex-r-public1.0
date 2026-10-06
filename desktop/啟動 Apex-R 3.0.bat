@echo off
chcp 65001 >nul
cd /d "%~dp0"

if exist "Apex-R-3.0.exe" (
    start "" "Apex-R-3.0.exe"
    exit /b 0
)

if exist "dist\Apex-R-3.0\Apex-R-3.0\Apex-R-3.0.exe" (
    start "" "dist\Apex-R-3.0\Apex-R-3.0\Apex-R-3.0.exe"
    exit /b 0
)

echo Apex-R 3.0 — 啟動圖形介面（RDyn-W / Top10 / U65 / M120）
where py >nul 2>&1
if %errorlevel%==0 (
    py -3.13 monitor_gui.py 2>nul
    if %errorlevel%==0 goto :end
    py -3 monitor_gui.py 2>nul
    if %errorlevel%==0 goto :end
)

where python >nul 2>&1
if %errorlevel%==0 (
    python monitor_gui.py
    goto :end
)

echo 找不到 Apex-R-3.0.exe 或 Python。請先執行 build_exe.ps1 打包。
pause

:end
