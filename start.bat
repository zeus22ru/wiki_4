@echo off
chcp 65001 >nul
cd /d "%~dp0"

echo ========================================
echo Запуск/перезапуск Wiki QA проекта
echo ========================================

:: Останавливаем предыдущий Telegram worker (если был запущен через start.bat)
tasklist /FI "WINDOWTITLE eq Telegram Worker*" 2>nul | find /I "python.exe" >nul
if %ERRORLEVEL% EQU 0 (
    echo.
    echo [!] Остановка предыдущего Telegram worker...
    taskkill /FI "WINDOWTITLE eq Telegram Worker*" /F >nul 2>&1
    echo [OK] Telegram worker остановлен
    timeout /t 1 /nobreak >nul
)

:: Останавливаем предыдущее веб-приложение (порт 5000)
netstat -ano | findstr :5000 | findstr LISTENING >nul
if %ERRORLEVEL% EQU 0 (
    echo.
    echo [!] Порт 5000 занят
    echo [!] Освобождение порта...
    for /f "tokens=5" %%a in ('netstat -ano ^| findstr :5000 ^| findstr LISTENING') do (
        taskkill /F /PID %%a >nul 2>&1
    )
    echo [OK] Порт освобожден
    timeout /t 2 /nobreak >nul
)

:: Запускаем веб-приложение в отдельном окне
echo.
echo [+] Запуск веб-приложения...
start "Wiki QA" python web_app.py
echo [OK] Веб-приложение: http://localhost:5000

:: Даём веб-приложению время подняться перед стартом worker
timeout /t 3 /nobreak >nul

:: Запуск Telegram worker, если включён в .env
if exist .env (
    findstr /i /r /c:"^TELEGRAM_ENABLED=true" .env >nul 2>&1
    if not errorlevel 1 (
        echo [+] TELEGRAM_ENABLED=true — запуск Telegram worker...
        start "Telegram Worker" python scripts/telegram_bot_worker.py
        echo [OK] Telegram worker запущен
    ) else (
        echo [i] Telegram worker не запущен (TELEGRAM_ENABLED не равен true в .env)
    )
) else (
    echo [i] Telegram worker не запущен (файл .env не найден)
)

echo.
echo ========================================
echo Готово. Окна Wiki QA и Telegram Worker работают отдельно.
echo Для остановки закройте соответствующие окна или нажмите Ctrl+C в них.
echo ========================================
echo.
pause
