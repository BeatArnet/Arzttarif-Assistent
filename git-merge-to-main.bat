@echo off
chcp 65001 >nul
powershell.exe -NoLogo -ExecutionPolicy Bypass -File "git-merge-to-main.ps1"
pause