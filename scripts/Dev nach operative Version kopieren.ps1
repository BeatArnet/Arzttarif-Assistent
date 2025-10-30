<#!
.SYNOPSIS
    Uebertraegt den aktuellen Entwicklungsstand in das lokale Produktions-Repository.

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

function Assert-Success {
    param(
        [int]$ExitCode,
        [string]$Message
    )

    if ($ExitCode -ne 0) {
        throw $Message
    }
}

function Get-GitSafeTagName {
    param([string]$Version)

    if (-not $Version) {
        throw "Versionsstring fuer Git-Tag fehlt."
    }

    $candidate = $Version -replace '[^0-9A-Za-z._-]+', '-'
    $candidate = $candidate.Trim('-')

    if (-not $candidate) {
        throw "Versionsstring '$Version' konnte nicht in einen gueltigen Git-Tag-Namen umgewandelt werden."
    }

    git check-ref-format --branch $candidate | Out-Null
    Assert-Success $LASTEXITCODE "Automatisch erzeugter Tag-Name '$candidate' ist ungueltig."

    return $candidate
}

$RepoUrl = "https://github.com/BeatArnet/Arzttarif-Assistent"

if (-not (Test-Path $DevPath)) {
    Write-Error "Entwicklungsverzeichnis '$DevPath' wurde nicht gefunden."
    exit 1
}

try {
    $configPath = Join-Path $DevPath 'config.ini'
    $Version = Get-AppVersion -IniPath $configPath
    $TagName = Get-GitSafeTagName -Version $Version
} catch {
    Write-Error $_
    exit 1
}

if (-not (Test-Path $ProdPath)) {
    git clone $RepoUrl $ProdPath
    Assert-Success $LASTEXITCODE "git clone '$RepoUrl' nach '$ProdPath' fehlgeschlagen."
}

$previousLocation = Get-Location

try {
    Set-Location $ProdPath

    if ($TagName -ne $Version) {
        Write-Host "Hinweis: Verwende Git-Tag '$TagName' fuer Version '$Version'."
    }

    git fetch origin
    Assert-Success $LASTEXITCODE "git fetch origin fehlgeschlagen."

    git checkout $Branch
    Assert-Success $LASTEXITCODE "git checkout $Branch fehlgeschlagen."

    git pull --ff-only origin $Branch
    Assert-Success $LASTEXITCODE "git pull --ff-only origin $Branch fehlgeschlagen."

    # Alte Dateien (ausser .git) entfernen
    # Produktionsarbeitsverzeichnis leeren, aber ``.git`` unangetastet lassen.
    Get-ChildItem -Force | Where-Object { $_.Name -ne '.git' } | Remove-Item -Recurse -Force

    git clean -xdf
    Assert-Success $LASTEXITCODE "git clean -xdf fehlgeschlagen."

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
    Assert-Success $LASTEXITCODE "git add . fehlgeschlagen."

    $statusOutput = git status --porcelain
    Assert-Success $LASTEXITCODE "git status --porcelain fehlgeschlagen."

    if (-not $statusOutput) {
        Write-Warning "Keine Aenderungen festgestellt. Commit, Push und Tagging wurden ausgelassen."
        return
    }

    git commit -m "Release Version $Version"
    Assert-Success $LASTEXITCODE "git commit fehlgeschlagen."

    git push origin $Branch
    Assert-Success $LASTEXITCODE "git push origin $Branch fehlgeschlagen."

    $existingTag = git tag --list $TagName
    Assert-Success $LASTEXITCODE "git tag --list $TagName fehlgeschlagen."

    if ($existingTag) {
        Write-Warning "Tag $TagName existiert bereits. Push des Tags wurde uebersprungen."
    } else {
        git tag $TagName
        Assert-Success $LASTEXITCODE "git tag $TagName fehlgeschlagen."

        git push origin $TagName
        Assert-Success $LASTEXITCODE "git push origin $TagName fehlgeschlagen."
    }

    Write-Host "[OK] Deployment von Version $Version abgeschlossen (Tag: $TagName)."
} finally {
    Set-Location $previousLocation
}
