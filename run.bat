@echo off
setlocal
chcp 65001 >nul
title Rain Classroom Resource Exporter V2.0
echo Rain Classroom Resource Exporter V2.0
cd /d "%~dp0"
if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" bootstrap.py %*
  goto finished
)
py -3 -c "import sys,struct; assert sys.version_info >= (3,9) and struct.calcsize('P') == 8" >nul 2>&1
if not errorlevel 1 (
  py -3 bootstrap.py %*
  goto finished
)
python -c "import sys,struct; assert sys.version_info >= (3,9) and struct.calcsize('P') == 8" >nul 2>&1
if not errorlevel 1 (
  python bootstrap.py %*
  goto finished
)
echo Install 64-bit Python 3.9+ from https://www.python.org/downloads/windows/
echo Include Tcl/Tk and the Python launcher. Then run this file again.
pause
exit /b 1
:finished
set "YKT_EXIT_CODE=%ERRORLEVEL%"
if not "%YKT_EXIT_CODE%"=="0" (
  echo Startup failed. See README.md for setup and troubleshooting.
  pause
)
exit /b %YKT_EXIT_CODE%
