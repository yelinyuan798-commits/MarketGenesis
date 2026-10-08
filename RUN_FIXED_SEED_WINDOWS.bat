@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
  py -m venv .venv 2>nul || python -m venv .venv
  if errorlevel 1 goto :fail
)

".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto :fail
".venv\Scripts\python.exe" reproduce.py
if errorlevel 1 goto :fail

start "" "reproduced\打开查看结果.html"
echo.
echo MarketGenesis fixed-seed reproduction completed.
pause
exit /b 0

:fail
echo.
echo Reproduction failed. Please keep this window open and send the error output.
pause
exit /b 1
