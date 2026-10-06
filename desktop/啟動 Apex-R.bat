@echo off
chcp 65001 >nul
cd /d "%~dp0"

echo Apex-R 4.0 — 啟動圖形介面
call "%~dp0_ensure_python.bat"
if errorlevel 1 exit /b 1

%PYCMD% monitor_gui.py
if errorlevel 1 (
    echo.
    echo 程式異常結束，請把上方錯誤訊息回報。
    pause
)
