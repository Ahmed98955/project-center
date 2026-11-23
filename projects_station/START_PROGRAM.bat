@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
title Projects Station

set "PY="
where py >nul 2>nul && set "PY=py -3"
if not defined PY where python >nul 2>nul && set "PY=python"
if not defined PY goto nopython
%PY% -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>nul
if errorlevel 1 goto nopython

if not exist ".venv\Scripts\python.exe" (
  echo [1/2] Creating local environment - first run only...
  %PY% -m venv .venv
  if errorlevel 1 goto fail
)
".venv\Scripts\python.exe" -c "import fastapi, uvicorn, multipart, pypdf" >nul 2>nul
if errorlevel 1 (
  echo [2/2] Installing components - first run only...
  ".venv\Scripts\python.exe" -m pip install --disable-pip-version-check --no-index --find-links wheels -r requirements.txt
  if errorlevel 1 ".venv\Scripts\python.exe" -m pip install --disable-pip-version-check -r requirements.txt
  if errorlevel 1 goto fail
)

".venv\Scripts\python.exe" run.py %*
if errorlevel 1 goto fail
exit /b 0

:nopython
echo.
echo  Python 3.10 or newer is required.
echo  Download it from https://www.python.org/downloads/
echo  During setup tick "Add python.exe to PATH", then run this file again.
echo.
pause
exit /b 1

:fail
echo.
echo  Startup failed. See the messages above.
pause
exit /b 1
