@echo off
chcp 65001 >nul
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Please set up the environment described in PHASE1.md.
  pause
  exit /b 1
)
".venv\Scripts\python.exe" -c "import PIL; import playwright" >nul 2>&1
if errorlevel 1 (
  ".venv\Scripts\python.exe" -m pip install -r requirements.txt
  if errorlevel 1 (
    pause
    exit /b 1
  )
)
".venv\Scripts\python.exe" main.py --gui %*
if errorlevel 1 pause
