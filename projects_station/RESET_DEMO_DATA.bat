@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo This deletes all entered data and restores the prototype (demo) data.
set /p ANS=Type YES to continue: 
if /I not "%ANS%"=="YES" exit /b 0
call START_PROGRAM.bat --reset
