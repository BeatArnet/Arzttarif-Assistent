<#
    Deploy-V1.1.ps1
    Kopiert die aktuelle Entwicklerversion in das lokale Produktionsrepo
    und entfernt zuvor alle alten Dateien. Wird das Entwicklungsverzeichnis
    nicht gefunden, bricht das Skript ab.
#>

param(
    [string]$DevPath  = $PSScriptRoot,
    [string]$ProdPath = "C:\Users\beata\OneDrive\Dokumente\Organisation\OAAT\Neuer_Arzttarif\GPT-Assistent\Arzttarif_Assistent",
    [string]$Branch   = "main"
)

$RepoUrl = "https://github.com/BeatArnet/Arzttarif-Assistent"
$Version = "v3.0"

if (-not (Test-Path $DevPath)) {
    Write-Error "Entwicklungsverzeichnis '$DevPath' wurde nicht gefunden."
    exit 1
}

if (-not (Test-Path $ProdPath)) {
    git clone $RepoUrl $ProdPath
}

Set-Location $ProdPath
git fetch origin
git checkout $Branch
git pull origin $Branch

# Alte Dateien (ausser .git) entfernen
Get-ChildItem -Force | Where-Object { $_.Name -ne '.git' } | Remove-Item -Recurse -Force
git clean -xdf

# Dateien kopieren, .git auslassen
try {
    $sourceItems = Get-ChildItem -Path $DevPath -Force -Exclude '.git'
    foreach ($item in $sourceItems) {
        Copy-Item -Path $item.FullName -Destination $ProdPath -Recurse -Force -ErrorAction Stop
    }
} catch {
    Write-Error "Kopieren fehlgeschlagen: $_"
    exit 1
}

git add .
git commit -m "Release Version $Version"
git push origin $Branch
git tag $Version
git push origin $Version

Write-Host "✅ Deployment von Version $Version abgeschlossen."
