@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"
title Projects Station + Commander Screen

echo Starting both programs - each opens its own browser tab.
echo.

set "STATION_BAT="
if exist "projects_station_part1\projects_station\START_PROGRAM.bat" set "STATION_BAT=projects_station_part1\projects_station\START_PROGRAM.bat"
if not defined STATION_BAT if exist "projects_station\START_PROGRAM.bat" set "STATION_BAT=projects_station\START_PROGRAM.bat"

set "CMD_BAT="
if exist "command_screen\START_COMMAND.bat" set "CMD_BAT=command_screen\START_COMMAND.bat"
if not defined CMD_BAT if exist "command_screen_part2\START_COMMAND.bat" set "CMD_BAT=command_screen_part2\START_COMMAND.bat"

if defined STATION_BAT start "Projects Station" cmd /k "%STATION_BAT%"
if defined CMD_BAT start "Commander Screen" cmd /k "%CMD_BAT%"

if not defined STATION_BAT echo [WARNING] Projects Station folder not found.
if not defined CMD_BAT echo [WARNING] Commander Screen folder not found.
echo.
echo Close this window - the two programs keep running in their own windows.
pause
