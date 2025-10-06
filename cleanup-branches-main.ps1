<#
.SYNOPSIS
    Bereinigt veraltete Git-Branches lokal und auf allen Remotes.

.DESCRIPTION
    Wechselt auf ``main``, holt die neuesten Referenzen, entfernt alle nicht in
    ``$keep`` aufgeführten Branches und pruned Remote-Branches. Praktisch nach
    grösseren Merge-Serien, um das Repository schlank zu halten.
#>

[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$env:GIT_GC_DISABLED = "1"

$keep = @('main')
# Bei Bedarf um weitere langfristige Branches ergänzen.

Write-Host "Wechsle auf main …"
git checkout main

Write-Host "Fetch + Prune …"
git fetch --all --prune --tags

Write-Host "========= LOKALE BRANCHES ========="
git branch --format='%(refname:short)' |
Where-Object { $_ -notin $keep } |
ForEach-Object {
    Write-Host "Lösche lokalen Branch $_"
    git branch -D $_
}

Write-Host "========= REMOTE BRANCHES ========="
foreach ($remote in git remote) {
    git remote prune $remote
    git for-each-ref --format='%(refname:strip=3)' "refs/remotes/$remote" |
    Where-Object { $_ -ne 'HEAD' -and $_ -notin $keep } |
    ForEach-Object {
        Write-Host "Lösche Remote-Branch $remote/$_"
        git push $remote --delete $_
    }
}

Write-Host "Bereinige losgelöste Referenzen …"
git reflog expire --expire=now --all

Write-Host "Packe Objekte (ohne Verzeichnislöschung) …"
git repack -a -f -q

Write-Host "`n✅ Bereinigt. Behaltene Branches: $($keep -join ', ')"
