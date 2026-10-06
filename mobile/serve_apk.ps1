@echo off
chcp 65001 >nul
cd /d "%~dp0dist"
if not exist "*.apk" (
  echo 找不到 APK。請先執行 build_apk.ps1。
  pause
  exit /b 1
)
echo 同一 Wi-Fi 下，手機瀏覽器開啟下方網址下載 APK：
for /f "tokens=2 delims=:" %%a in ('ipconfig ^| findstr /c:"IPv4"') do (
  set IP=%%a
  goto :found
)
:found
set IP=%IP: =%
echo.
echo   http://%IP%:8080/
echo.
echo 按 Ctrl+C 停止伺服器
py -3.13 -m http.server 8080
