@echo off
chcp 65001 >nul
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo 请先建立 Python 3.9+ 虚拟环境并安装 requirements.txt 和 Chromium。
  pause
  exit /b 1
)
".venv\Scripts\python.exe" main.py %*
pause
