@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo Apex-R mobile preview (Flet)...
where py >nul 2>&1 && (py -3.13 -m pip install -r requirements.txt -q & py -3.13 main.py) || python main.py
pause
