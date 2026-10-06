@echo off
chcp 65001 >nul
cd /d "%~dp0"

set "CFG=%~dp0config.yaml"
if not exist "%CFG%" set "CFG=%~dp0dist\Apex-R\config.yaml"
if not exist "%CFG%" set "CFG=%~dp0dist\Apex-R-new\Apex-R\config.yaml"

echo 更新 Apex-R 美股宇宙（兩年成交額）...
echo 設定檔: %CFG%

where py >nul 2>&1
if %errorlevel%==0 (
  py -3.13 refresh_universe.py --config "%CFG%" 2>nul || py -3 refresh_universe.py --config "%CFG%" || py refresh_universe.py --config "%CFG%"
) else (
  python refresh_universe.py --config "%CFG%"
)

if errorlevel 1 (
  echo.
  echo 失敗。請在專案資料夾執行，並確認已安裝 Python 3。
  pause
  exit /b 1
)
echo.
echo 完成。請開啟 Apex-R.exe 使用最新宇宙。
pause
