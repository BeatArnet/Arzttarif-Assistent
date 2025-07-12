[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8

# Git-Änderungen abrufen
git fetch --all

# Lokale Branches anzeigen
Write-Host "Verfuegbare lokale Branches:"
git branch

# Benutzer nach Branch fragen
$branchName = Read-Host "Welchen Branch moechten Sie in 'main' mergen?"

# Prüfen, ob Branch existiert
if (-not (git show-ref --verify --quiet "refs/heads/$branchName")) {
    Write-Host "Fehler: Branch '$branchName' nicht gefunden." -ForegroundColor Red
    exit 1
}

# Zu main wechseln
git checkout main

# Mergen
git merge $branchName
if ($LASTEXITCODE -ne 0) {
    Write-Host "Fehler beim Mergen. Bitte Konflikte beheben und Merge manuell abschliessen." -ForegroundColor Red
    exit 1
}

# Push
git push origin main
if ($LASTEXITCODE -ne 0) {
    Write-Host "Fehler beim Pushen zu 'main'." -ForegroundColor Red
    exit 1
}

# Optionales Löschen des Branches
$delete = Read-Host "Moechten Sie den Branch '$branchName' lokal loeschen? (j/n)"
if ($delete -eq 'j') {
    git branch -d $branchName
    Write-Host "Branch '$branchName' wurde lokal geloescht." -ForegroundColor Green
}

Write-Host "Merge und Push erfolgreich abgeschlossen." -ForegroundColor Green
