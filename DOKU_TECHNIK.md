# Technische Dokumentation
Hinweise ab Version 3.1–3.3
- LLM-Aufrufe über generischen Wrapper (`openai_wrapper.chat_completion_safe`) für Gemini, OpenAI, Apertus (OpenAI-kompatibel), Ollama-kompatibel.
- Stage‑2 mit separaten Temperaturen für Mapping/Ranking: `stage2_mapping_temperature`, `stage2_ranking_temperature` (in `config.ini`).
- Granulares Logging unter `[LOGGING]` (u. a. LLM‑Eingabe/Prompt/Output, Tokenzähler; Rotations‑Logging).
- Endpoint `/api/version` liefert App‑ und Tarifversion.
- Details zu UI‑Änderungen und Fixes siehe `CHANGELOG.md`.

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

## 7. Dateien (Python/JS/HTML)

### Backend (Python)
- `server.py` – Flask‑Backend, Routen (`/api/*`, statisch), Orchestrierung Stage‑1/2, Regelprüfungen, Logging, Feedback‑API, `/api/version`.
- `regelpruefer_einzelleistungen.py` – Regeln für TARDOC‑Einzelleistungen (Mengen, Kumulationen, Patientenbedingungen) und Aufbereitung der Abrechnung.
- `regelpruefer_pauschale.py` – Pauschalen‑Bedingungen prüfen, Detail‑HTML generieren, Auswahl der passenden Pauschale.
- `utils.py` – Hilfsfunktionen: HTML‑Escapes, Sprachfelder, Tabellen‑Lookups, Übersetzungen, Tokenstatistiken, Ranking‑/Suchhelfer (RAG).
- `prompts.py` – Prompt‑Vorlagen für Stage‑1 (Extraktion) und Stage‑2 (Mapping/Ranking) in DE/FR/IT.
- `openai_wrapper.py` – Stabiler OpenAI‑kompatibler Chat‑Wrapper (Temperatur‑Handling, Throttling via `[LLM]`, User‑Agent, Fallbacks für Parameternamen).
- `generate_embeddings.py` – Erzeugt `data/leistungskatalog_embeddings.json` für den RAG‑Modus (benötigt `sentence-transformers`).
- `llm_vergleich.py` – Vergleicht Provider/Modelle anhand `llm_vergleich_results.json` und `data/baseline_results.json` (Korrektheit/Laufzeit/Tokenverbrauch).
- `run_quality_tests.py` – Führt QS‑Beispiele gegen Baseline durch und zeigt Tokenverbrauch an.
- `clean_json.py` – Entfernt Steuerzeichen aus JSON‑Dateien und schreibt `*.clean.json` (Import‑Helfer).
- `update_prompts.py` – Zielgerichtete Text‑Korrekturen in `prompts.py` per `str.replace` mit Sicherheitsprüfungen.

### Frontend (JS/HTML)
- `index.html` – Haupt‑UI (Formulareingabe, Sprache, ICD/CHOP/GTIN, Ergebnisdarstellung, Feedback‑Button).
- `calculator.js` – Frontend‑Steuerung der Analyse, UI‑Interaktionen, API‑Aufrufe (`/api/analyze-billing`, ICD/CHOP).
- `quality.html` – UI für Qualitätstests mit Beispielen.
- `quality.js` – Steuert `quality.html`, lädt Testfälle und ruft `/api/quality` auf.

### Synonyms‑Paket (Python/GUI)
- `synonyms/__main__.py` – Startpunkt `python -m synonyms`: Tkinter‑GUI für Generierung, Kuration, Vergleich, Embeddings‑Export.
- `synonyms/synonyms_tk.py` – GUI‑Dialoge/Widgets für Katalog‑Bearbeitung.
- `synonyms/diff_view.py` – Vergleich zweier Katalogstände, Hervorhebung (neu/gelöscht/geändert).
- `synonyms/generator.py` – Generiert Synonymvorschläge aus Tarifdaten per LLM (Provider/Temperatur via `config.ini`).
- `synonyms/expander.py` – Erweitert Suchanfragen um Synonyme (Backend‑Nutzung), Schalter zum Aktivieren/Deaktivieren.
- `synonyms/storage.py` – Laden/Speichern verschiedener Katalog‑Formate; Normalisierung, Indizes, Toleranz bei Encodings.
- `synonyms/models.py` – Strukturierte Modelle für Synonymkatalog und Einträge.
- `synonyms/scorer.py` – Scoring/Ranking von Synonymvorschlägen.
- `synonyms/api.py` – Minimaler Flask‑Blueprint (`/api/synonyms/*`) als Entwicklungs‑Stub.
- `synonyms/__init__.py` – Paketinitialisierung.

### Tests (pytest)
- `tests/test_server.py` – Tests für Analyse‑Endpoint, LKN‑Parsing, Internationalisierung des Kontexts, Feedback‑Fallback, `/api/version`.
- `tests/test_chop_endpoint.py` – Tests für `/api/chop`.
- `tests/test_icd_endpoint.py` – Tests für `/api/icd`.
- `tests/test_truncate_text.py` – Tests für Texthandling/Trunkierung (Kontextbeschränkung).
- `tests/test_pauschale_logic.py` – Logische Prüfung der Pauschalenbedingungen.
- `tests/test_pauschale_search.py` – Suche/Matching für Pauschalen (tokenbasiert/Keywords).
- `tests/test_pauschale_selection.py` – Auswahl der anwendbaren Pauschale aus Kandidaten.
- `tests/test_regelpruefer_einzelleistungen.py` – Einzelleistungs‑Regelwerk (Mengen/Kumulationen etc.).
- `tests/test_llm_connectivity.py` – Erreichbarkeit/Wrapper‑Verhalten für LLM‑Provider (Stubs/Mocks).
- `tests/test_llm_vergleich_providers.py` – Szenarien für `llm_vergleich.py` (Provider/Modelle).
- `tests/test_compare_catalogues.py` – Vergleich von Katalogständen (z. B. für Synonyme/Diff‑View).
- `tests/test_synonyms_expander.py` – Tests für Anfrage‑Erweiterung durch Synonyme.
- `tests/test_synonyms_generator.py` – Tests für Generierung/Temperaturen/Provider‑Auswahl.
- `tests/test_synonyms_storage.py` – Laden/Speichern/Normalisieren des Synonymkatalogs.
- `tests/test_synonyms_models.py` – Modellstruktur/Validierung.
- `tests/test_synonyms_evaluation.py` – Qualität/Scoring von Synonymvorschlägen.

---

Dieses Dokument bietet einen technischen Einstieg in die wichtigsten Komponenten des Projekts. Für Detailfragen empfiehlt sich ein Blick in die jeweiligen Quelltexte und die README‑Datei.
