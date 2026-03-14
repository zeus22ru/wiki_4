@echo off
chcp 65001 >nul
echo ========================================
echo Запуск/перезапуск Wiki QA проекта
echo ========================================

:: Проверяем, запущен ли процесс Python с web_app.py
tasklist /FI "IMAGENAME eq python.exe" /FI "WINDOWTITLE eq *web_app.py*" 2>nul | find /I "python.exe" >nul
if %ERRORLEVEL% EQU 0 (
    echo.
    echo [!] Найден запущенный процесс Python
    echo [!] Остановка предыдущего процесса...
    for /f "tokens=2" %%i in ('tasklist /FI "IMAGENAME eq python.exe" /FI "WINDOWTITLE eq *web_app.py*" /NH 2^>nul ^| find /I "python.exe"') do (
        taskkill /F /PID %%i >nul 2>&1
    )
    echo [OK] Процесс остановлен
    timeout /t 2 /nobreak >nul
)

:: Проверяем, занят ли порт 5000
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

:: Запускаем приложение
echo.
echo [+] Запуск веб-приложения...
echo [+] Приложение будет доступно по адресу: http://localhost:5000
echo.
echo Для остановки нажмите Ctrl+C
echo ========================================
echo.

python web_app.py

pause
