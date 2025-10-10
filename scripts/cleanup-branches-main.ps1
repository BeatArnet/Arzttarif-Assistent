<#
.SYNOPSIS
    Bereinigt veraltete Git-Branches lokal und auf allen Remotes.

.DESCRIPTION
    Wechselt auf "main", holt die neuesten Referenzen, entfernt alle nicht in
    $Keep aufgefuehrten lokalen Branches und loescht entsprechende Remote-Branches.
    Danach Reflogs bereinigen und Objekte neu packen.
#>

[CmdletBinding()]
param(
    [string[]]$Keep = @('main')
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$env:GIT_GC_DISABLED = "1"

function Invoke-Git {
    param(
        [Parameter(Mandatory)]
        [string[]]$GitArgs
    )
    $pinfo = New-Object System.Diagnostics.ProcessStartInfo
    $pinfo.FileName = "git"
    $pinfo.Arguments = ($GitArgs -join " ")
    $pinfo.RedirectStandardOutput = $true
    $pinfo.RedirectStandardError  = $true
    $pinfo.UseShellExecute = $false
    $pinfo.CreateNoWindow = $true
    $proc = New-Object System.Diagnostics.Process
    $proc.StartInfo = $pinfo
    [void]$proc.Start()
    $stdout = $proc.StandardOutput.ReadToEnd()
    $stderr = $proc.StandardError.ReadToEnd()
    $proc.WaitForExit()
    if ($proc.ExitCode -ne 0) {
        throw "git $($GitArgs -join ' ') failed: $stderr"
    }
    return $stdout.TrimEnd()
}

# 1) Repository-Pruefung
if (-not (Invoke-Git @('rev-parse','--is-inside-work-tree'))) {
    throw "Kein Git-Repository im aktuellen Verzeichnis."
}

# 2) Auf main wechseln
$current = Invoke-Git @('rev-parse','--abbrev-ref','HEAD')
if ($current -ne 'main') {
    Write-Host "Wechsle auf main ..."
    Invoke-Git @('checkout','main')
}

# 3) Fetch + Prune
Write-Host "Fetch + Prune ..."
Invoke-Git @('fetch','--all','--prune','--tags')

# 4) Lokale Branches
Write-Host "========= LOKALE BRANCHES ========="
$localBranches = Invoke-Git @('for-each-ref','--format=%(refname:short)','refs/heads')
$localBranches = $localBranches -split "`n" | Where-Object { $_ -and ($_ -ne 'HEAD') }

foreach ($b in $localBranches) {
    if ($b -in $Keep) { continue }
    if ($b -eq $current) { continue }
    Write-Host "Loesche lokalen Branch $b"
    Invoke-Git @('branch','-D',$b)
}

# 5) Remote-Branches
Write-Host "========= REMOTE BRANCHES ========="
$remotes = (Invoke-Git @('remote')) -split "`n" | Where-Object { $_ }

foreach ($remote in $remotes) {
    Write-Host "Prune $remote ..."
    Invoke-Git @('remote','prune',$remote)

    $remoteBranches = Invoke-Git @('for-each-ref','--format=%(refname:strip=3)',"refs/remotes/$remote")
    $remoteBranches = $remoteBranches -split "`n" | Where-Object { $_ -and ($_ -ne 'HEAD') }

    foreach ($rb in $remoteBranches) {
        if ($rb -in $Keep) { continue }
        Write-Host "Loesche Remote-Branch $remote/$rb"
        try {
            Invoke-Git @('push',$remote,'--delete',$rb)
        } catch {
            Write-Host "Hinweis: Konnte $remote/$rb nicht loeschen: $($_.Exception.Message)"
        }
    }
}

# 6) Aufraeumen
Write-Host "Bereinige Reflogs ..."
Invoke-Git @('reflog','expire','--expire=now','--all')

Write-Host "Packe Objekte ..."
Invoke-Git @('repack','-a','-f','-q')

Write-Host ""
Write-Host "Bereinigt. Behaltene Branches: $($Keep -join ', ')"
