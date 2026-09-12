@echo off
setlocal EnableExtensions
chcp 65001 >nul

cd /d "%~dp0"
title Wiki update

echo ========================================
echo   Updating XWiki knowledge base
echo ========================================
echo.

rem Use system Python because the local .venv may point to an old installation.
set "PYTHON=python"

echo [1/2] Exporting pages from XWiki...
%PYTHON% scripts\parse_xwiki.py --include-space sa --include-space 1c --include-space faq
if errorlevel 1 (
    echo.
    echo ERROR: XWiki export failed.
    echo Check XWiki availability and XWIKI_USERNAME/XWIKI_PASSWORD in .env.
    pause
    exit /b 1
)

echo.
echo [2/2] Updating search index...
%PYTHON% create_vector_db.py
if errorlevel 1 (
    echo.
    echo ERROR: search index update failed.
    pause
    exit /b 1
)

echo.
echo DONE: XWiki data and search index were updated.
pause
endlocal
