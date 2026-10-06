@echo off
rem shinsegi SNS automation scheduler - runs independent of WorkBuddy.
rem KST 06:00 / 12:00 content cycles, 10:00 metrics collection.
rem Keep this window open while the scheduler runs. Close it to stop.
cd /d "%~dp0"
"C:\Users\ROYcp\.workbuddy\binaries\python\envs\default\Scripts\python.exe" -m src.main schedule
pause
