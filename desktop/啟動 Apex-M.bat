@echo off
chcp 65001 >nul
cd /d "%~dp0"

echo ========================================
echo   Apex-M v1.0 — R0 純動能，學術基準
echo   與 Apex-R 4.0 / RDyn-W 分開，避免混淆
echo ========================================
echo.

call "%~dp0_ensure_python.bat"
if errorlevel 1 exit /b 1

%PYCMD% monitor_gui.py --config "%~dp0config_apex_m.yaml"
if errorlevel 1 (
    echo.
    echo 程式異常結束，請把上方錯誤訊息回報。
    pause
)
