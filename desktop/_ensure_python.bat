@echo off
REM Finds a working Python, sets PYCMD, and installs missing packages.
REM Usage:  call "%~dp0_ensure_python.bat"
REM         if errorlevel 1 exit /b 1
set "PYCMD="

where py >nul 2>&1
if not errorlevel 1 (
    py -3.13 -c "import sys" >nul 2>&1
    if not errorlevel 1 set "PYCMD=py -3.13"
)
if not defined PYCMD (
    where py >nul 2>&1
    if not errorlevel 1 (
        py -3 -c "import sys" >nul 2>&1
        if not errorlevel 1 set "PYCMD=py -3"
    )
)
if not defined PYCMD (
    python -c "import sys" >nul 2>&1
    if not errorlevel 1 set "PYCMD=python"
)
if not defined PYCMD (
    echo 找不到可用的 Python。
    echo 請安裝 Python 3.10 以上版本，安裝時務必勾選 Add python.exe to PATH。
    echo 下載：https://www.python.org/downloads/
    pause
    exit /b 1
)

%PYCMD% -c "import tkinter" >nul 2>&1
if errorlevel 1 (
    echo 這個 Python 缺少 tkinter，無法顯示圖形介面。
    echo 請重新安裝 Python，並勾選 tcl/tk and IDLE 選項。
    pause
    exit /b 1
)

%PYCMD% -c "import pandas, numpy, pytz, yaml, yfinance, matplotlib" >nul 2>&1
if errorlevel 1 (
    echo 首次執行：正在安裝必要套件，需要網路，約 1 到 3 分鐘...
    %PYCMD% -m pip install -r "%~dp0requirements.txt"
    if errorlevel 1 (
        echo.
        echo 套件安裝失敗，請把上方訊息回報。
        pause
        exit /b 1
    )
)
exit /b 0
