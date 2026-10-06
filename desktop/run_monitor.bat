@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo 啟動 Apex-R 監控（命令列版）...
where py >nul 2>&1
if %errorlevel%==0 (
  py -3.13 monitor_local.py --config "%~dp0config.yaml" 2>nul || py -3 monitor_local.py --config "%~dp0config.yaml"
) else (
  python monitor_local.py --config "%~dp0config.yaml"
)
pause
