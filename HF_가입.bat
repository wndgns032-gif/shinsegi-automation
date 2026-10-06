@echo off
rem Double-click to open the HuggingFace signup window (Chrome profile kept in data\_hfprofile)
rem You only need to solve the picture CAPTCHA; the rest is automatic.
cd /d "%~dp0"
"C:\Users\ROYcp\.workbuddy\binaries\python\envs\default\Scripts\python.exe" -u scripts\hf_setup.py open 5400
echo.
echo --- account info ---
type data\hf_account.json
pause
