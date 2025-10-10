Hilfsskripte für Entwicklung und Operations

- `cleanup-branches-main.ps1`
  - Räumt lokale und Remote‑Branches auf (Whitelist per `-Keep`).
  - Führt `git checkout main`, `git fetch --all --prune`, löscht Branches und bereinigt Reflogs/Packs.

- `git-merge-to-main.ps1`
  - Geführter `--no-ff`‑Merge eines lokalen Branches nach `main` inkl. Push.
  - Fragt interaktiv den Branch ab; zeigt Fehler und Hinweise an.

- `Dev nach operative Version kopieren.ps1`
  - Kopiert den aktuellen Dev‑Stand in ein lokales Produktions‑Repository, committed, pusht und erstellt ein Tag.
  - Parameter: `-DevPath`, `-ProdPath`, `-Branch`.

- `clean_json.py`
  - Entfernt Steuerzeichen aus JSON‑Dateien und schreibt `<name>.clean.json`.
  - Nutzung: `python scripts/clean_json.py <pfad/zur/datei.json>`

Hinweise
- Skripte sind optional und verändern lokale Repositories/Dateien. Vor Ausführung Pfade/Parameter prüfen.
- Erfordern Git und passende Rechte. Ausführung z. B.: `powershell -ExecutionPolicy Bypass -File scripts/<skript>.ps1`.
- Für Python‑Hilfen: aktivierte venv verwenden, z. B. `venv\Scripts\python scripts\clean_json.py data\file.json`.
