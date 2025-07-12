@echo off
chcp 65001 >nul
REM Merge der aktuellen 'dev'-Branch nach 'main' – lokal und remote

REM Hole ersten Remote-Namen
FOR /F "delims=" %%r IN ('git remote') DO (
    SET "REMOTE=%%r"
    GOTO REMOTE_FOUND
)
:REMOTE_FOUND

IF "%REMOTE%"=="" (
    echo ❌ Kein Remote-Repository gefunden.
    pause
    exit /b
)

echo 🔄 Hole letzte Änderungen von Remote...
git fetch %REMOTE%

echo ⏳ Wechsel auf 'main'...
git checkout main

echo 🔁 Aktualisiere 'main' mit Remote-Änderungen...
git pull %REMOTE% main

echo ✅ Merge von 'dev' in 'main' wird durchgeführt...
git merge dev

IF ERRORLEVEL 1 (
    echo ❌ Merge fehlgeschlagen – bitte Konflikte manuell lösen.
    pause
    exit /b
)

echo 📤 Push auf Remote-Branch 'main'...
git push %REMOTE% main

echo.
echo ✅ 'main' enthält nun die aktuelle Version von 'dev'.
pause
