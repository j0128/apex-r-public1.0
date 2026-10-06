@echo off
chcp 65001 >nul
cd /d "%~dp0"

echo AI 投資委員會日報（Apex-M × Apex-R）
where py >nul 2>&1
if %errorlevel%==0 (
    py -3.13 daily_committee_report.py --via gmail %*
    goto :end
)
where python >nul 2>&1
if %errorlevel%==0 (
    python daily_committee_report.py --via gmail %*
    goto :end
)
echo 找不到 Python。
pause
:end
