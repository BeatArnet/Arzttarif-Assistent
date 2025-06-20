@echo off
setlocal enabledelayedexpansion

:: ======= KONFIGURATION =======
set "REMOTE=origin"
set "MAIN_BRANCH=main"
set /p PR_ID=Gib die PR-Nummer von Codex ein (z.B. 18): 
set "LOCAL_BRANCH=codex-fix-%PR_ID%"
:: =============================

echo.
echo [1/5] Hole PR # %PR_ID% vom Remote-Repo...
git fetch %REMOTE% pull/%PR_ID%/head:%LOCAL_BRANCH%

echo.
echo [2/5] Wechsel in lokalen Codex-Branch: %LOCAL_BRANCH%
git checkout %LOCAL_BRANCH%

echo.
echo [3/5] Hole neuesten Stand von %MAIN_BRANCH%
git fetch %REMOTE%
git merge %REMOTE%/%MAIN_BRANCH%

echo.
echo [4/5] Falls Konflikte auftreten, bitte jetzt manuell auflösen.
pause

echo.
echo [5/5] Änderungen committen und pushen...
git add .
git commit -m "Merge %MAIN_BRANCH% into %LOCAL_BRANCH% and resolve conflicts"
git push %REMOTE% %LOCAL_BRANCH%

echo.
echo ✅ Codex-PR ist aktualisiert und kann ohne Konflikte gemerged werden.
pause
