@echo off
cd /d "C:\Users\piard\Desktop\PragmaProject"
title Pragma - Otonom Kantitatif Trade Motoru
color 0a
echo ======================================================================
echo  PRAGMA v1.0 OTONOM TICARET SISTEMI BASLATILIYOR...
echo  - Mod 1: Sanal Islem Defteri (Shadow Trader)
echo  - Mod 2: Canli Begonya Forex/Emtia Nobetcisi (run_pipeline)
echo ======================================================================

set PYTHON_EXE=C:\Users\piard\AppData\Local\Programs\Python\Python312\python.exe

:: 1. Sanal Islem Defterini (Shadow Trader) ayri bir pencerede baslat
start "Pragma - Shadow Trader" "%PYTHON_EXE%" -m pragma.shadow_trader --poll-seconds 10 --bars 3000 --heartbeat-minutes 0

:: 2. Canli Begonya Watcher'i bu ana pencerede baslat
"%PYTHON_EXE%" -u -m pragma.run_pipeline --scan-begonya --refresh-macro --watch --interval-sec 15

pause
