@echo off
setlocal
chcp 65001 >nul
set "PYTHONUTF8=1"
title Strata Dual RX 7900 XTX MTP Vision 1M - port 8080
echo ================================================================
echo   Qwen3.8 Flash Next IQ4_XS - dual RX 7900 XTX - MTP - Vision ON
echo   Context: 1M (1048576 tokens)
echo   Testing build. See the desktop validation report.
echo   Dashboard: http://<PC-LAN-IP>:8080/
echo   Local: http://127.0.0.1:8080/v1
echo   LAN:   http://<PC-LAN-IP>:8080/v1
echo   Bind:  0.0.0.0:8080
echo   Run one Strata launcher at a time. Ctrl+C to stop.
echo ================================================================
cd /d "D:\codex-work\strata-win-20261107"
"%LOCALAPPDATA%\Programs\Python\Python312\python.exe" -X utf8 "D:\anan-work\Strata-rdna3-fixed\serve\server.py" --engine strata --config "D:\codex-work\strata-win-20261107\dual7900-mtp-vision-1m-test.json" --host 0.0.0.0 --port 8080
echo.
echo The server stopped.
pause
