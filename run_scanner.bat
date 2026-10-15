@echo off
setlocal
cd /d "%~dp0"
if exist "%~dp0.venv\Scripts\python.exe" (
    set "PYTHON_EXE=%~dp0.venv\Scripts\python.exe"
) else (
    set "PYTHON_EXE=python"
)
echo Starting Pragma multi-market scanner...
echo Scan interval: 15 minutes
echo Keep MetaTrader 5 open and logged in.
"%PYTHON_EXE%" -m pragma.market_scanner --interval-minutes 15 --bars 3000
pause
