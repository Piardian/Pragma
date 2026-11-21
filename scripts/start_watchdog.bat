@echo off
title PRAGMA UNIFIED WATCHDOG
cd /d "C:\Users\piard\Desktop\PragmaProject"

echo ======================================================
echo   PRAGMA UNIFIED MULTI-PROJECT WATCHDOG & HEARTBEAT
echo   Monitors: Pragma, Trawma, Megalord, Begonya, Stigma, MT5
echo ======================================================

set PYTHON_EXE=C:\Users\piard\AppData\Local\Programs\Python\Python312\python.exe

"%PYTHON_EXE%" -m pragma.watchdog --watch --interval-sec 60 --heartbeat-hours 2 --stale-threshold-sec 900
pause
