@echo off
chcp 65001 >nul
cd /d "%~dp0"

if exist "Apex-R-4.0.exe" (
    start "" "Apex-R-4.0.exe"
    exit /b 0
)

if exist "dist\Apex-R-4.0\Apex-R-4.0\Apex-R-4.0.exe" (
    start "" "dist\Apex-R-4.0\Apex-R-4.0\Apex-R-4.0.exe"
    exit /b 0
)

REM fallback legacy 3.0 build names
if exist "Apex-R-3.0.exe" (
    start "" "Apex-R-3.0.exe"
    exit /b 0
)

echo Apex-R 4.0 — 啟動圖形介面，RDyn-W / Top10 / U60 / M120
call "%~dp0_ensure_python.bat"
if errorlevel 1 exit /b 1

%PYCMD% monitor_gui.py
if errorlevel 1 (
    echo.
    echo 程式異常結束，請把上方錯誤訊息回報。
    pause
)
