@echo off
title SEO Tool - myvapez.de
cd /d "%~dp0"

REM Virtuelle Umgebung aktivieren
if exist .venv\Scripts\activate.bat (
    call .venv\Scripts\activate.bat
) else (
    echo Virtuelle Umgebung nicht gefunden. Erstelle sie jetzt...
    python -m venv .venv
    call .venv\Scripts\activate.bat
    echo Installiere Abhaengigkeiten...
    pip install -r requirements.txt
)

echo.
echo ========================================
echo   SEO Tool startet...
echo   Browser oeffnet sich automatisch.
echo   Zum Beenden: STRG+C druecken
echo ========================================
echo.

streamlit run app.py
pause
