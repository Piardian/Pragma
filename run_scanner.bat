@echo off
setlocal
cd /d "%~dp0"
echo Starting Pragma multi-market scanner...
echo Scan interval: 15 minutes
echo Keep MetaTrader 5 open and logged in.
python -m pragma.market_scanner --interval-minutes 15 --bars 3000
pause
