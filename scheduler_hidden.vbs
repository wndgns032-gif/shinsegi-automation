' 창 없이 스케줄러를 띄운다 (Windows 작업 스케줄러 / 더블클릭 둘 다 가능).
' 이미 떠 있는 인스턴스가 있으면 파일 락 때문에 새 인스턴스는 즉시 종료된다.
Option Explicit
Dim sh, root, py, cmd
Set sh = CreateObject("WScript.Shell")

root = "C:\Users\ROYcp\WorkBuddy\2026-09-18-20-03-59\sns-automation"
py   = "C:\Users\ROYcp\.workbuddy\binaries\python\envs\default\Scripts\python.exe"

sh.CurrentDirectory = root
sh.Environment("PROCESS")("PYTHONIOENCODING") = "utf-8"
cmd = """" & py & """ -u -m src.main schedule >> """ & root & "\data\scheduler.log"" 2>&1"
' 0 = 창 숨김, False = 종료 기다리지 않음
sh.Run "cmd.exe /c " & cmd, 0, False
