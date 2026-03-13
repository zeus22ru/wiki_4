@echo off
chcp 65001 >nul
echo ========================================
echo Сборка WikiQA в исполняемый файл
echo ========================================
echo.

REM Проверка наличия Python
python --version >nul 2>&1
if errorlevel 1 (
    echo [ОШИБКА] Python не найден. Установите Python и добавьте его в PATH.
    pause
    exit /b 1
)

echo [1/4] Установка зависимостей...
pip install -r requirements.txt
if errorlevel 1 (
    echo [ОШИБКА] Не удалось установить зависимости.
    pause
    exit /b 1
)
echo.

echo [2/4] Проверка наличия векторной базы данных...
if not exist "chroma_db" (
    echo [ПРЕДУПРЕЖДЕНИЕ] Векторная база данных не найдена.
    echo Запустите create_vector_db.py для создания базы данных.
    echo.
)

echo [3/4] Сборка исполняемого файла с помощью PyInstaller...
pyinstaller --clean wiki_qa.spec
if errorlevel 1 (
    echo [ОШИБКА] Не удалось собрать исполняемый файл.
    pause
    exit /b 1
)
echo.

echo [4/4] Копирование дополнительных файлов...
if exist "chroma_db" (
    xcopy /E /I /Y "chroma_db" "dist\WikiQA\chroma_db" >nul
    echo   - Векторная база данных скопирована
)

if exist ".env" (
    copy /Y ".env" "dist\WikiQA\" >nul
    echo   - Файл .env скопирован
)

echo.
echo ========================================
echo Сборка завершена успешно!
echo ========================================
echo.
echo Исполняемый файл находится в: dist\WikiQA.exe
echo.
echo Для запуска на другом ПК:
echo 1. Скопируйте папку dist\WikiQA на целевой компьютер
echo 2. Запустите WikiQA.exe
echo 3. Откройте браузер и перейдите на http://localhost:5000
echo.
echo ВАЖНО: Для работы приложения требуется установленный Ollama
echo Скачать: https://ollama.ai/download
echo.
pause
