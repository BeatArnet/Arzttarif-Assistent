# Entwicklungsleitfaden

Dieser kurze Leitfaden beschreibt das Einrichten der Entwicklungsumgebung und das Ausführen der automatisierten Tests.

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

