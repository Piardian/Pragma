@echo off
setlocal
cd /d "%~dp0"
if exist "%~dp0.venv\Scripts\python.exe" (
    set "PYTHON_EXE=%~dp0.venv\Scripts\python.exe"
) else (
    set "PYTHON_EXE=python"
)
echo Starting Pragma broker-free shadow trader...
echo MT5 is used only as a read-only market data source. No broker orders are sent.
"%PYTHON_EXE%" -m pragma.shadow_trader --poll-seconds 10 --bars 3000
