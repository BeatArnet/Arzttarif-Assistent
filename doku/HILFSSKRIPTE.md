Hilfsskripte

Dieses Dokument beschreibt optionale Hilfsskripte im Verzeichnis `scripts/`.

- cleanup-branches-main.ps1
  - Räumt lokale und Remote‑Branches auf (Whitelist per `-Keep`).
  - Beispiel: `powershell -ExecutionPolicy Bypass -File scripts/cleanup-branches-main.ps1 -Keep main,release`

- git-merge-to-main.ps1
  - Geführter Merge eines lokalen Branches nach `main` (`--no-ff`) inkl. Push nach `origin/main`.
  - Aufruf: `powershell -ExecutionPolicy Bypass -File scripts/git-merge-to-main.ps1`

- Dev nach operative Version kopieren.ps1
  - Kopiert den aktuellen Dev‑Stand in ein lokales Produktions‑Repository, committed, pusht und erstellt ein Tag.
  - Parameter: `-DevPath`, `-ProdPath`, `-Branch` (Standard `main`). Vor Nutzung `ProdPath` prüfen/anpassen.

- clean_json.py
  - Entfernt Steuerzeichen aus JSON‑Dateien und schreibt `<name>.clean.json` neben die Originaldatei.
  - Aufruf: `python scripts/clean_json.py <pfad/zur/datei.json>` (ggf. mit aktivierter venv)

Zusätzliche Qualitätsrunner (Projekt-Root)
- run_quality_tests.py
  - Führt Baseline-Beispiele aus `data/baseline_results.json` gegen `/api/test-example` aus und zeigt Laufzeit-/Tokenstatistiken.
  - Aufruf: `python run_quality_tests.py`

- run_pauschalen_quality_control.py
  - Führt harte Datenchecks für `data/PAUSCHALEN_Logic.json` aus und erzeugt Reports.
  - Artefakte: `quality_reports/pauschalen_quality_report.json` und `quality_reports/pauschalen_quality_report.html`.
  - Aufruf: `python run_pauschalen_quality_control.py`

Hinweise
- Skripte sind optional und können lokale Repositories/Dateien verändern. Vor Ausführung Pfade/Parameter prüfen.
- PowerShell‑Skripte erfordern eine Git‑Installation und passende Rechte.
