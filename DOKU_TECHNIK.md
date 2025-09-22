# Technische Dokumentation

Diese Datei gibt einen Überblick über die Architektur und den Code des Arzttarif‑Assistenten. Sie richtet sich an Entwickler, die sich schnell im Projekt zurechtfinden möchten.

## 1. Gesamtübersicht

Die Anwendung besteht aus einem Python‑Backend (Flask) und einem HTML/JavaScript‑Frontend. Nutzer geben im Browser eine medizinische Leistungsbeschreibung ein. Das Backend ruft anschliessend ein Large‑Language‑Model auf (konfigurierbar: z. B. Gemini, OpenAI, SwissAI/Apertus, Ollama‑kompatibel), prüft die resultierenden Leistungspositionen mit lokalen Regeln und entscheidet, ob eine Pauschale oder einzelne TARDOC‑Leistungen verrechnet werden sollen. Die Ergebnisse werden als JSON an das Frontend zurückgegeben und dort dargestellt.

Grober Ablauf:

1. **Frontend (`index.html`, `calculator.js`)** sammelt Eingaben (Freitext, ICD/GTIN, Alter, Geschlecht).
2. **Backend (`server.py`)**
   - ruft `call_gemini_stage1()` auf, um mögliche Leistungspositionen (LKN) und Kontext zu erkennen.
   - führt Regelprüfungen in `regelpruefer_einzelleistungen.py` und `regelpruefer_pauschale.py` aus.
   - wählt eine passende Pauschale oder erstellt eine TARDOC‑Abrechnung.
3. **Antwort** inkl. Details zur Regelprüfung wird an das Frontend gesendet und angezeigt.

## 2. Projektstruktur

- `server.py` – zentrale Flask‑Applikation und API‑Endpoints.
- `regelpruefer_einzelleistungen.py` – Prüfung der TARDOC‑Regeln pro Leistung.
- `regelpruefer_pauschale.py` – Logik zur Prüfung von Pauschalen.
- `utils.py` – Hilfsfunktionen (z. B. Übersetzungen, Textaufbereitung, Keyword‑Extraktion).
- `calculator.js` / `quality.js` – Frontend‑Logik und Aufruf der API.
- `data/` – JSON‑Dateien mit Tarif‑ und Testdaten.
- `tests/` – Pytest‑basierte Unittests und Beispielaufrufe.

## 3. Wichtige Python‑Funktionen

### server.py

- `create_app()` – Initialisiert die Flask‑Instanz und lädt die JSON‑Daten einmalig.
- `load_data()` – Liest alle Dateien aus dem `data/`‑Verzeichnis ein (Leistungskatalog, TARDOC, Pauschalen usw.).
- `call_stage1()` (anbieterspezifisch) – Kommuniziert mit dem konfigurierten LLM‑Provider (u. a. Gemini, OpenAI, Apertus) und liefert LKN‑Vorschläge und Kontext.
- API‑Endpoints:
  - `/api/analyze-billing` – Hauptendpunkt zur Analyse eines Freitexts.
  - `/api/chop` – Suchfunktion für CHOP‑Codes.
  - `/api/icd` – ICD‑Lookup.
  - `/api/quality` – Vergleich von Beispielrechnungen mit Baseline‑Ergebnissen.
  - `/api/test-example` – führt einen Beispieltest gegen `baseline_results.json` aus.
  - `/api/submit-feedback` – Speichert Feedback lokal oder erstellt GitHub‑Issues.
  - Optional: `/api/synonyms/*` – Blueprint für künftige Synonym‑Operationen.

### regelpruefer_einzelleistungen.py

- `lade_regelwerk()` – lädt das Regelwerk für Einzelleistungen.
- `pruefe_abrechnungsfaehigkeit()` – überprüft Mengenbeschränkungen, Kumulationen und Patientenbedingungen.
- `prepare_tardoc_abrechnung()` – fasst regelkonforme Leistungen für die spätere Abrechnung zusammen.

### regelpruefer_pauschale.py

- `evaluate_pauschale_logic_orchestrator()` – prüft, ob alle Bedingungen einer Pauschale erfüllt sind.
- `determine_applicable_pauschale()` – wählt anhand von Regeln und Prioritäten die beste Pauschale aus.
- `generate_condition_detail_html()` – erzeugt HTML‑Berichte für die einzelnen Bedingungen.

### utils.py

Enthält verschiedenste Helfer:
- `expand_compound_words()` – zerlegt zusammengesetzte Wörter für bessere LLM‑Erkennung.
- `extract_keywords()` – liefert Schlüsselbegriffe aus einem Text, wobei Synonyme berücksichtigt werden.
- `compute_token_doc_freq()` und `rank_leistungskatalog_entries()` – unterstützen das Ranking von LKN anhand der Texte im Leistungskatalog.
- Zusätzlich einfache Übersetzungen (`translate`, `translate_rule_error_message`) und HTML‑Hilfen.

### Synonymverwaltung

Der Synonymkatalog liegt in `data/synonyms.json` und wird beim Start des
Servers geladen. Das Paket im Verzeichnis `synonyms/` bietet einen GUI‑Editor,
der über `python -m synonyms` gestartet wird, um neue Vorschläge zu erzeugen
oder Einträge zu kuratieren. Über den Abschnitt `[SYNONYMS]` in `config.ini`
lässt sich steuern, ob die Liste genutzt wird und wie sie heisst. Die Synonyme
fliessen in die Stichwortsuche sowie in den Aufbau der Embeddings ein.

### RAG-Modus und Embeddings

Ab Version 2.6 kann der Kontext für das LLM stark verkleinert werden. Dazu werden
Vektordarstellungen des Leistungskatalogs mit `generate_embeddings.py` erzeugt
(`sentence-transformers` erforderlich) und als `leistungskatalog_embeddings.json`
gespeichert. Ist in `config.ini` unter `[RAG]` der Wert `enabled = 1` gesetzt,
werden beim Aufruf von `/api/analyze-billing` nur die passendsten Einträge an das
LLM geschickt.
Ohne RAG umfasst der Prompt mehr als 600 000 Tokens; mit RAG genügen rund 10 000.

Der Embedding‑Generator berücksichtigt dabei auch Synonyme. `generate_embeddings.py`
lädt den Synonymkatalog aus `data/synonyms.json` und fügt alle dort hinterlegten
Varianten den Beschreibungstexten der jeweiligen LKN hinzu, bevor der Vektor
berechnet wird. Dadurch landet jede bekannte Formulierung der Leistung im
Embedding und steht später für die semantische Suche zur Verfügung.

Bei der Ermittlung der Leistungskandidaten für LLM 1 nutzt `server.py`
dieselben Synonyme: über `expand_query` werden Eingaben des Nutzers um passende
Begriffe ergänzt, direkte Treffer in der Synonymliste liefern sofort die
zugehörigen LKN‑Codes. Die Embedding‑Suche verwendet hingegen ausschliesslich den
vorverarbeiteten Originaltext ohne Synonym‑Erweiterung.

### LLM‑Vergleich

Das Skript `llm_vergleich.py` testet verschiedene LLM-Provider und Modelle gegen
die in `data/baseline_results.json` hinterlegten Beispiele. In
`llm_vergleich_results.json` lässt sich pro Stufe ein eigener Provider und ein
eigenes Modell (`Stage1Provider`/`Stage1Model` bzw. `Stage2Provider`/`Stage2Model`)
angeben; fehlen diese Felder, gelten `Provider` und `Model` für beide Stufen. Für
jede Konfiguration werden Korrektheitsquote, Laufzeit und der benötigte
Tokenumfang ermittelt und im JSON gespeichert, sodass sich Kosten und Qualität
gegenüberstellen lassen.

## 4. Frontend

`calculator.js` und `index.html` bilden die Hauptoberfläche. Die Texte der Benutzeroberfläche werden aus `translations.json` geladen. Über `/api/analyze-billing` wird die Berechnung gestartet. `quality.js` bedient die Testseite `quality.html` und ruft `/api/quality` auf.

## 5. Tests und Qualitätssicherung

Die wichtigsten Tests liegen im Verzeichnis `tests/` und prüfen sowohl API‑Endpunkte als auch die Pauschalenlogik. Zusätzlich existiert `run_quality_tests.py`, das Beispieltexte gegen erwartete Baseline‑Ergebnisse vergleicht. Die Tests können mit

```bash
pytest
```

ausgeführt werden.

## 6. Daten und Konfiguration

Im Ordner `data/` liegen sämtliche JSON‑Dateien für Leistungskatalog, TARDOC‑Informationen und Pauschalen. Grosse Dateien werden über Git LFS versioniert. API‑Keys für den gewählten LLM‑Provider werden in einer `.env`‑Datei hinterlegt (z. B. `GEMINI_API_KEY`, `OPENAI_API_KEY`, `APERTUS_API_KEY`; optional `*_BASE_URL`). Weitere optionale Variablen (`GITHUB_TOKEN`, `GITHUB_REPO`) ermöglichen die automatische Erstellung von Feedback‑Issues.

### LLM‑Provider und Token‑Budget

Die Stufen‑Konfiguration erfolgt in `config.ini` unter `[LLM1UND2]` (`stage1_provider/_model`, `stage2_provider/_model`). Für OpenAI‑kompatible Provider (OpenAI, Apertus) stehen Budget‑ und Trimm‑Parameter unter `[OPENAI]` zur Verfügung; für Gemini entsprechende Optionen unter `[GEMINI]`. Über `[CONTEXT]` lässt sich der Kontextumfang granular steuern (`include_*`, `max_context_items`, `force_include_codes`).

### Aktualisierung der Datenbasis

Synonyme und Embeddings sind direkt an die Version des Leistungskatalogs gebunden. Die mitgelieferte `synonyms.json` wurde aus den Beschreibungen des `LKAAT_Leistungskatalog.json` erstellt. Sobald dieser Katalog oder andere Daten aktualisiert werden, muss der Synonymkatalog neu generiert werden, z. B. mit

```
python -m synonyms.cli generate --output data/synonyms.json
```

oder per GUI mit `python synonyms/synonyms.py`. Anschliessend müssen die Embeddings über

```
python generate_embeddings.py
```

neu erstellt werden, damit die Suche neue LKNs und Begriffe berücksichtigt.

### Dateiumbenennungen ab Version 1.1

Seit Version 1.1 tragen viele JSON-Dateien neue Namen. Die wichtigsten Änderungen:

| Alter Name                         | Neuer Name                          |
|------------------------------------|-------------------------------------|
| `tblLeistungskatalog.json`         | `LKAAT_Leistungskatalog.json`       |
| `tblPauschaleLeistungsposition.json` | `PAUSCHALEN_Leistungspositionen.json` |
| `tblPauschalen.json`               | `PAUSCHALEN_Pauschalen.json`        |
| `tblPauschaleBedingungen.json`     | `PAUSCHALEN_Bedingungen.json`       |
| `tblTabellen.json`                 | `PAUSCHALEN_Tabellen.json`          |
| `TARDOCGesamt_optimiert_Tarifpositionen.json` | `TARDOC_Tarifpositionen.json` und `TARDOC_Interpretationen.json` |

---

Dieses Dokument bietet einen technischen Einstieg in die wichtigsten Komponenten des Projekts. Für Detailfragen empfiehlt sich ein Blick in die jeweiligen Quelltexte und die README‑Datei.
