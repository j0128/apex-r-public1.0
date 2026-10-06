@echo off
chcp 65001 >nul
cd /d "%~dp0desktop"
echo Apex-R 4.0 — 啟動桌面版（desktop\）
if exist "啟動 Apex-R 4.0.bat" (
  call "啟動 Apex-R 4.0.bat"
) else (
  call "啟動 Apex-R.bat"
)
