@echo off
REM ============================================================
REM  YouTube channel auth  -  run on YOUR PC
REM
REM  Why: the sandboxed agent runs in an isolated network, so
REM       Google's OAuth callback (127.0.0.1) never reaches it.
REM       This script runs on your real machine, so it works.
REM
REM  Usage:  double-click, or run from PowerShell:
REM      .\scripts\youtube_auth.cmd ko
REM ============================================================

cd /d "C:\Users\ROYcp\WorkBuddy\2026-09-18-20-03-59\sns-automation"

set YT_NO_BROWSER=1
set YT_AUTH_TIMEOUT=1800
set PYTHONIOENCODING=utf-8

REM ---------------------------------------------------------
REM  Local proxy breaks the OAuth callback on this PC.
REM  HTTP_PROXY=127.0.0.1:6222 makes Google route even
REM  127.0.0.1 callbacks through the proxy, so the reply
REM  never reaches this window. Clear it here.
REM ---------------------------------------------------------
set HTTP_PROXY=
set http_proxy=
set HTTPS_PROXY=
set https_proxy=
set ALL_PROXY=
set all_proxy=
set NO_PROXY=127.0.0.1,localhost,::1
set no_proxy=127.0.0.1,localhost,::1

set PY=C:\Users\ROYcp\.workbuddy\binaries\python\envs\default\Scripts\python.exe

if not exist "%PY%" (
  echo [ERROR] python not found: %PY%
  pause
  exit /b 1
)

echo ============================================================
echo  YouTube channel auth : %1
echo ============================================================
echo.
echo  A URL will appear below in a few seconds.
echo  Copy it into your browser address bar.
echo.
echo  --- WHICH ACCOUNT TO PICK ---
echo    zh-cn   shinsegimedia account  ->  @shinsegi-zh
echo    ko      Roy personal account   ->  @WisdomPathroad
echo    en      Roy personal account   ->  @wisdompath-en
echo    fr      shinsegimedia account  ->  @shinsegi-fr
echo.
echo  - Pick the Google account FIRST, then the channel.
echo  - Google may preselect the wrong account. Check carefully.
echo.
echo  IF YOU SEE "ERR_CONNECTION_REFUSED" or "refused to connect":
echo    1) Keep THIS WINDOW OPEN. Closing it kills the callback server.
echo    2) The URL must be opened within the waiting time.
echo    3) Use the URL printed in THIS window (not an old one).
echo    4) If you use Chrome/Edge and it fails again, type this
echo       directly in the address bar (replace 1234 with the port
echo       shown in this window):
echo         http://localhost:1234/
echo       You should NOT get "refused to connect".
echo
echo  IF YOU SEE "403 access_denied / app is testing":
echo    The OAuth consent screen is in TESTING mode.
echo    Fix it here (one time, about 1 min):
echo    https://console.cloud.google.com/
echo      -> project "shinsegi"
echo      -> APIs and Services ^> OAuth consent screen
echo      -> either
echo         (a) Publishing status  ->  "In production"
echo         (b) Test users         ->  add these accounts:
echo               shinsegimedia@gmail.com
echo               + your personal Gmail
echo    Then run this file again.
echo
echo  "Access blocked" at the very end is NORMAL - it means success.
echo  Do not close this window. Waits up to 30 minutes.
echo.

"%PY%" -u scripts\youtube_auth.py %1

echo.
echo ============================================================
echo  exit code: %ERRORLEVEL%
echo  Check the result above. Then tell your agent.
echo ============================================================
pause
