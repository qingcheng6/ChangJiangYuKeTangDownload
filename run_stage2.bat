@echo off
chcp 65001 >nul
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo 请先按 PHASE1.md 建立环境。
  pause
  exit /b 1
)
".venv\Scripts\python.exe" main.py --gui %*
if errorlevel 1 pause
