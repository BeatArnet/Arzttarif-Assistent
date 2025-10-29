# Entwicklungsleitfaden

Dieser kurze Leitfaden beschreibt das Einrichten der Entwicklungsumgebung und das Ausführen der automatisierten Tests.

## Kurzüberblick: Hauptprozesse

- Vorverarbeitung: `expand_compound_words`, `extract_keywords`, optional `synonyms/expander.expand_query`; Ranking via Embeddings (RAG) oder Token‑Frequenz.
- LLM‑Stufe 1: Prompt aus `prompts.get_stage1_prompt`; Aufruf `call_gemini_stage1`/`call_openai_stage1`; Rückgabe JSON (`identified_leistungen`, `extracted_info`, `begruendung_llm`).
- Regeln (Einzelleistungen): `regelpruefer_einzelleistungen.pruefe_abrechnungsfaehigkeit` normalisiert Mengen, prüft Kumulationen/Patienten/ICD.
- Pauschalen (Stufe 2): Mapping/Ranking `call_*_stage2_*`; Hauptprüfung `regelpruefer_pauschale.check_pauschale_conditions` + `evaluate_pauschale_logic_orchestrator`; Auswahl `determine_applicable_pauschale`.
- Ergebnis: ggf. Pauschale mit Regel‑HTML + regelkonforme LKN; Logging/Tokenmessung je nach `[LOGGING]` aktiv.

## Abhängigkeiten installieren

Die Tests benötigen Flask sowie die weiteren Pakete aus `requirements.txt`. Installation:

```bash
pip install -r requirements.txt
```

## Tests ausführen

Nach der Installation der Abhängigkeiten können die Tests mit

```bash
pytest -q
```

gestartet werden. Die Tests liegen im Verzeichnis `tests/` und basieren auf der Flask-Anwendung `server.py`.

### Ausführung – konkrete Programmaufrufe

- Windows (PowerShell)
  - `py -3 -m venv venv`
  - `.\venv\Scripts\Activate.ps1`
  - `python -m pip install -r requirements.txt`
  - `python -m pytest -q`

- macOS/Linux (Bash/Zsh)
  - `python3 -m venv venv`
  - `source venv/bin/activate`
  - `python -m pip install -r requirements.txt`
  - `python -m pytest -q`

Weitere nützliche Aufrufe
- Einzelne Datei: `python -m pytest tests/test_pauschale_logic.py -q`
- Einzelner Test: `python -m pytest tests/test_pauschale_logic.py::test_kumuliert_korrekt -q`
- Filtern per Ausdruck: `python -m pytest -k "synonyms and not connectivity" -q`
- Mehr Ausgabe/Logs: `python -m pytest -vv -s`
- Nur Synonym‑Tests: `python -m pytest tests -k synonyms -q`
- LLM‑Konnektivitätstests auslassen: `python -m pytest -k "not llm_connectivity" -q`

## Dateicodierung

- Alle Textdateien werden als UTF‑8 ohne BOM gespeichert.
- Bei Anzeigeproblemen mit Umlauten das Repository einmalig normalisieren:
  `python scripts/normalize_encoding.py`.
- Für reine Prüfungen ohne Änderungen `--dry-run` ergänzen.
- Vor dem Commit `python scripts/normalize_encoding.py --dry-run` ausführen, um unbeabsichtigte Rückfälle zu erkennen.

LLM‑Konnektivität aktivieren (optional)
- Setze je nach Provider API‑Keys und ggf. Base‑URLs:
  - PowerShell: `setx GEMINI_API_KEY "..."`; für die aktuelle Session: `$env:GEMINI_API_KEY="..."`
  - PowerShell: `$env:OPENAI_API_KEY="..."`, `$env:APERTUS_API_KEY="..."`
  - Optional: `$env:APERTUS_BASE_URL="https://api.publicai.co/v1"`, `$env:OPENAI_BASE_URL="https://api.openai.com/v1"`
- Danach: `python -m pytest -k llm_connectivity -q`

## Versionierung und Changelog

- Aktuelle Version: 3.4 (siehe `config.ini` oder Endpoint `/api/version`).
- Ausführliche Änderungen und Migrationshinweise: `CHANGELOG.md`.
- Größere Featurebereiche seit 3.1: granulare Logging-Flags (`[LOGGING]`), getrennte Temperaturen für Stage‑2 (`stage2_mapping_temperature`, `stage2_ranking_temperature`).

## Synonymverwaltung

Synonyme liegen in `data/synonyms.json`. Zur Pflege kann der GUI‑Editor gestartet werden mit

```bash
python -m synonyms
```

Nach Änderungen sollte der Server neu gestartet und – falls der RAG‑Modus aktiv ist – die Embeddings neu erzeugt werden.

## LLM-Vergleich

Zum Benchmark verschiedener Sprachmodelle können in `llm_vergleich_results.json` die gewünschten Provider und Modelle konfiguriert werden. Für jede Stufe lassen sich eigene Felder `Stage1Provider`/`Stage1Model` sowie `Stage2Provider`/`Stage2Model` angeben; fehlen sie, gelten `Provider` und `Model` für beide Stufen. Das Skript

```bash
python llm_vergleich.py
```

führt alle Beispiele aus `data/baseline_results.json` aus und schreibt Genauigkeit, Laufzeit und Tokenverbrauch zurück in die JSON-Datei.

## RAG-Workflow

Ist in `config.ini` der Abschnitt `[RAG]` mit `enabled = 1` gesetzt, lädt der Server die vorberechneten Embeddings aus `data/leistungskatalog_embeddings.json`, um den Kontext auf relevante Katalogeinträge zu beschränken. Sobald Katalog oder Synonyme geändert werden, sollten die Embeddings mit

```bash
python generate_embeddings.py
```

neu erzeugt werden.

## Pytest und Importpfade

- Bitte Tests mit `pytest` starten. Die Datei `tests/conftest.py` setzt den Repository‑Root automatisch auf `sys.path`, sodass `from synonyms...` in allen Tests funktioniert.
- Beim Ausführen einzelner Dateien ausserhalb von pytest (z. B. IDE‑Run‑Button) ist ggf. `PYTHONPATH` auf das Projekt‑Root zu setzen oder die IDE‑Option „Add content root to PYTHONPATH“ zu aktivieren.

Beispiele: PYTHONPATH temporär setzen und Tests starten
- Windows PowerShell (einzeilig):
  - `$env:PYTHONPATH = (Get-Location).Path; python -m pytest -q`
- Windows CMD:
  - `set PYTHONPATH=%cd% && python -m pytest -q`
- macOS/Linux (Bash/Zsh):
  - `PYTHONPATH="$(pwd)" python -m pytest -q`

## Hilfsskripte (PowerShell)

Zur Unterstützung von Entwicklungs- und Release-Abläufen stehen optionale PowerShell‑Skripte im Verzeichnis `scripts/` bereit. Diese sind nicht laufzeitkritisch und verändern lokale Git-Repositories oder kopieren Dateien – bitte mit Sorgfalt verwenden.

- `scripts/cleanup-branches-main.ps1`
  - Zweck: Lokale und Remote‑Branches aufräumen (außer Whitelist, standardmäßig `main`).
  - Beispiel: `powershell -ExecutionPolicy Bypass -File scripts/cleanup-branches-main.ps1 -Keep main,release`
  - Hinweise: Führt `git checkout main`, `git fetch --all --prune`, löscht lokale/Remote‑Branches und führt Reflog‑/Repack‑Aufräumen aus.

- `scripts/git-merge-to-main.ps1`
  - Zweck: Geführter Merge eines lokalen Branches nach `main` (inkl. Push).
  - Beispiel: `powershell -ExecutionPolicy Bypass -File scripts/git-merge-to-main.ps1`
  - Hinweise: Fragt interaktiv den zu mergenden Branch ab, führt `--no-ff` Merge aus und pusht nach `origin/main`.

- `scripts/Dev nach operative Version kopieren.ps1`
  - Zweck: Kopiert das aktuelle Dev‑Arbeitsverzeichnis in ein lokales Produktions‑Repository und erstellt Tag/Commit.
  - Parameter: `-DevPath <Pfad>` (default: Projektstamm), `-ProdPath <Zielrepo>`, `-Branch <main>`.
  - Hinweise: Standard‑`ProdPath` ist benutzer‑/systemabhängig; vor Nutzung prüfen/anpassen.

Alle Skripte setzen eine funktionierende Git‑Installation und passende Rechte voraus. Verwende vor dem Ausführen stets die korrekten Pfade/Parameter und prüfe die Konsolen‑Ausgaben.
