<#
.SYNOPSIS
    Überträgt den aktuellen Entwicklungsstand in das lokale Produktions-Repository.

.DESCRIPTION
    Klont bei Bedarf das Upstream-Repository, checkt den gewünschten Branch aus,
    entfernt alles ausser ``.git`` im Produktionsordner und kopiert danach die
    Entwicklungsdateien hinein. Anschliessend werden Änderungen gestaged,
    committed, gepusht und getaggt. Dieses Skript gleicht die Umgebung
    ``Arzttarif_Assistent`` vor der Übergabe an den Betrieb ab.
#>

param(
    # Standardmässig das Projektwurzelverzeichnis (Eltern von 'scripts') verwenden,
    # damit 'config.ini' gefunden wird, wenn das Skript via F5 gestartet wird.
    [string]$DevPath  = (Split-Path -Parent $PSScriptRoot),
    [string]$ProdPath = "C:\Users\beata\OneDrive\Dokumente\Organisation\OAAT\Neuer_Arzttarif\GPT-Assistent\Arzttarif_Assistent",
    [string]$Branch   = "main"
)

function Get-AppVersion {
    param([string]$IniPath)

    if (-not (Test-Path $IniPath)) {
        throw "Konfigurationsdatei '$IniPath' wurde nicht gefunden."
    }

    $currentSection = $null
    foreach ($line in Get-Content -Path $IniPath) {
        $trimmed = $line.Trim()
        if (-not $trimmed -or $trimmed.StartsWith(';') -or $trimmed.StartsWith('#')) {
            continue
        }

        if ($trimmed.StartsWith('[') -and $trimmed.EndsWith(']')) {
            $currentSection = $trimmed.Substring(1, $trimmed.Length - 2)
            continue
        }

        if ($currentSection -eq 'APP' -and $trimmed -match '^version\s*=\s*(.+)$') {
            $value = $matches[1].Trim()
            if ($value) {
                return "v$value"
            }
        }
    }

    throw "Keine Version im Abschnitt [APP] der Konfigurationsdatei '$IniPath' gefunden."
}

$RepoUrl = "https://github.com/BeatArnet/Arzttarif-Assistent"

if (-not (Test-Path $DevPath)) {
    Write-Error "Entwicklungsverzeichnis '$DevPath' wurde nicht gefunden."
    exit 1
}

try {
    $configPath = Join-Path $DevPath 'config.ini'
    $Version = Get-AppVersion -IniPath $configPath
} catch {
    Write-Error $_
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
# Produktionsarbeitsverzeichnis leeren, aber ``.git`` unangetastet lassen.
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
