@echo off
chcp 65001 >nul
cd /d "%~dp0"
setlocal EnableExtensions

echo ========================================
echo Запуск/перезапуск Wiki QA проекта
echo ========================================

:: Используем venv проекта (системный python обычно без зависимостей)
set "PYTHON_EXE=%~dp0.venv\Scripts\python.exe"
if not exist "%PYTHON_EXE%" (
    echo.
    echo [ERROR] Не найден .venv\Scripts\python.exe
    echo [ERROR] Создайте окружение и установите зависимости:
    echo         python -m venv .venv
    echo         .venv\Scripts\python.exe -m pip install -r requirements.txt
    echo.
    pause
    exit /b 1
)

:: Останавливаем предыдущий Telegram worker (если был запущен через start.bat)
tasklist /FI "WINDOWTITLE eq Telegram Worker*" 2>nul | find /I "cmd.exe" >nul
if %ERRORLEVEL% EQU 0 (
    echo.
    echo [!] Остановка предыдущего Telegram worker...
    taskkill /FI "WINDOWTITLE eq Telegram Worker*" /F >nul 2>&1
    echo [OK] Telegram worker остановлен
    ping -n 2 127.0.0.1 >nul
)

:: Останавливаем предыдущее веб-приложение (окно Wiki QA и/или порт 5000)
taskkill /FI "WINDOWTITLE eq Wiki QA*" /F >nul 2>&1
netstat -ano | findstr :5000 | findstr LISTENING >nul
if %ERRORLEVEL% EQU 0 (
    echo.
    echo [!] Порт 5000 занят
    echo [!] Освобождение порта...
    for /f "tokens=5" %%a in ('netstat -ano ^| findstr :5000 ^| findstr LISTENING') do (
        taskkill /F /PID %%a >nul 2>&1
    )
    echo [OK] Порт освобожден
    ping -n 3 127.0.0.1 >nul
)

:: Запускаем веб-приложение в отдельном окне (cmd /k — окно не закрывается при ошибке)
echo.
echo [+] Запуск веб-приложения через .venv...
start "Wiki QA" cmd /k ""%PYTHON_EXE%" web_app.py"
echo [OK] Веб-приложение: http://localhost:5000

:: Даём веб-приложению время подняться перед стартом worker
ping -n 4 127.0.0.1 >nul

:: Запуск Telegram worker, если включён в .env
set "TG_ENABLED=0"
if exist .env (
    findstr /i /r /c:"^TELEGRAM_ENABLED=true" .env >nul 2>&1
    if not errorlevel 1 set "TG_ENABLED=1"
)

if "%TG_ENABLED%"=="1" (
    echo [+] TELEGRAM_ENABLED=true — запуск Telegram worker...
    start "Telegram Worker" cmd /k ""%PYTHON_EXE%" scripts\telegram_bot_worker.py"
    echo [OK] Telegram worker запущен
) else if not exist .env (
    echo [i] Telegram worker не запущен: файл .env не найден
) else (
    echo [i] Telegram worker не запущен: TELEGRAM_ENABLED не равен true в .env
)

echo.
echo ========================================
echo Готово. Окна Wiki QA и Telegram Worker работают отдельно.
echo Для остановки закройте соответствующие окна или нажмите Ctrl+C в них.
echo ========================================
echo.
pause
endlocal
