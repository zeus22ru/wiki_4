@echo off
chcp 65001 >nul
cd /d "%~dp0"

powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts\start_project.ps1
if errorlevel 1 goto launch_error
exit /b 0

:launch_error
echo.
echo [ERROR] Wiki QA could not be started. See the message above.
pause
exit /b 1
