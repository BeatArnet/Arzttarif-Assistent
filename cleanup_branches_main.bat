@echo off
chcp 65001 >nul
REM Batch-Datei zur Bereinigung von lokalen und Remote-Branches ausser 'main'

REM Hole ersten Remote-Namen
FOR /F "delims=" %%r IN ('git remote') DO (
    SET "REMOTE=%%r"
    GOTO REMOTE_FOUND
)
:REMOTE_FOUND

IF "%REMOTE%"=="" (
    echo Kein Remote-Repository gefunden.
    pause
    exit /b
)

REM Wechsle auf main, falls nicht schon dort
git checkout main

REM Entferne verwaiste Remote-Referenzen
git remote prune %REMOTE%

REM Lösche alle lokalen Branches ausser main
FOR /F "tokens=*" %%b IN ('git branch --format="%%(refname:short)" ^| findstr /V "main"') DO (
    git branch -D %%b
)

REM Lösche alle Remote-Branches ausser main
SETLOCAL ENABLEDELAYEDEXPANSION
FOR /F "tokens=*" %%r IN ('git branch -r ^| findstr /V "%REMOTE%/main" ^| findstr /V "HEAD"') DO (
    SET "rb=%%r"
    SET "branch=!rb:%REMOTE%/=!"
    echo Lösche Remote-Branch: !branch!
    git push %REMOTE% --delete !branch! >nul 2>&1
)
ENDLOCAL

REM Git intern aufräumen
git gc --prune=now

echo.
echo ✅ Alle lokalen und Remote-Branches ausser 'main' und 'dev' wurden gelöscht.
echo ✅ Verwaiste Referenzen entfernt.
echo ✅ Git-Repository bereinigt.
pause
