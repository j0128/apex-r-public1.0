@echo off
chcp 65001 >nul
cd /d "%~dp0"

echo Apex-M CLI — R0 純動能報告
where py >nul 2>&1
if %errorlevel%==0 (
    py -3.13 monitor_local.py --config "%~dp0config_apex_m.yaml" %*
    goto :end
)
where python >nul 2>&1
if %errorlevel%==0 (
    python monitor_local.py --config "%~dp0config_apex_m.yaml" %*
    goto :end
)
echo 找不到 Python。
pause
:end
