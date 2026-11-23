@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
title Commander Screen

set "PY="
where py >nul 2>nul && set "PY=py -3"
if not defined PY where python >nul 2>nul && set "PY=python"
if not defined PY goto nopython
%PY% -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>nul
if errorlevel 1 goto nopython

rem --- pick a python that already has the dependencies ---
set "VENV_PY="
if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" -c "import fastapi, uvicorn, multipart" >nul 2>nul
  if not errorlevel 1 set "VENV_PY=.venv\Scripts\python.exe"
)
if not defined VENV_PY if exist "..\projects_station\.venv\Scripts\python.exe" (
  "..\projects_station\.venv\Scripts\python.exe" -c "import fastapi, uvicorn, multipart" >nul 2>nul
  if not errorlevel 1 set "VENV_PY=..\projects_station\.venv\Scripts\python.exe"
)
if not defined VENV_PY if exist "..\projects_station_part1\projects_station\.venv\Scripts\python.exe" (
  "..\projects_station_part1\projects_station\.venv\Scripts\python.exe" -c "import fastapi, uvicorn, multipart" >nul 2>nul
  if not errorlevel 1 set "VENV_PY=..\projects_station_part1\projects_station\.venv\Scripts\python.exe"
)

rem --- otherwise create our own environment ---
if not defined VENV_PY (
  echo [1/2] Creating local environment - first run only...
  %PY% -m venv .venv
  if errorlevel 1 goto fail
  set "VENV_PY=.venv\Scripts\python.exe"
  "%VENV_PY%" -c "import fastapi, uvicorn, multipart" >nul 2>nul
  if errorlevel 1 (
    echo [2/2] Installing components - first run only...
    "%VENV_PY%" -m pip install --disable-pip-version-check --no-index --find-links wheels -r requirements.txt
    if errorlevel 1 "%VENV_PY%" -m pip install --disable-pip-version-check -r requirements.txt
  )
)

"%VENV_PY%" -c "import fastapi, uvicorn, multipart" >nul 2>nul
if errorlevel 1 goto nodeps

"%VENV_PY%" run.py %*
if errorlevel 1 goto fail
exit /b 0

:nodeps
echo.
echo  Dependencies are missing and could not be installed.
echo  Make sure the Projects Station folder is next to this one
echo  (its environment will be reused), or connect to the internet
echo  and run this file again.
echo.
pause
exit /b 1

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
