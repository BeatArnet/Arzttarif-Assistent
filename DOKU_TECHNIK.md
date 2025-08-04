# Technische Dokumentation

Diese Datei gibt einen Überblick über die Architektur und den Code des Arzttarif‑Assistenten. Sie richtet sich an Entwickler, die sich schnell im Projekt zurechtfinden möchten.

## 1. Gesamtübersicht

Die Anwendung besteht aus einem Python‑Backend (Flask) und einem HTML/JavaScript‑Frontend. Nutzer geben im Browser eine medizinische Leistungsbeschreibung ein. Das Backend ruft anschliessend ein Large‑Language‑Model (Google Gemini) auf, prüft die resultierenden Leistungspositionen mit lokalen Regeln und entscheidet, ob eine Pauschale oder einzelne TARDOC‑Leistungen verrechnet werden sollen. Die Ergebnisse werden als JSON an das Frontend zurückgegeben und dort dargestellt.

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
- `call_gemini_stage1()` – Kommuniziert mit der Google‑Gemini‑API und liefert einen strukturierten Vorschlag an LKN und Kontextinformationen.
- API‑Endpoints:
  - `/api/analyze-billing` – Hauptendpunkt zur Analyse eines Freitexts.
  - `/api/chop` – Suchfunktion für CHOP‑Codes.
  - `/api/icd` – ICD‑Lookup.
  - `/api/quality` – Vergleich von Beispielrechnungen mit Baseline‑Ergebnissen.
  - `/api/test-example` – führt einen Beispieltest gegen `baseline_results.json` aus.
  - `/api/submit-feedback` – Speichert Feedback lokal oder erstellt GitHub‑Issues.

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

### RAG-Modus und Embeddings

Ab Version 2.6 kann der Kontext für das LLM stark verkleinert werden. Dazu werden
Vektordarstellungen des Leistungskatalogs mit `generate_embeddings.py` erzeugt
(`sentence-transformers` erforderlich) und als `leistungskatalog_embeddings.json`
gespeichert. Ist in `config.ini` unter `[RAG]` der Wert `enabled = 1` gesetzt,
werden beim Aufruf von `/api/analyze-billing` nur die passendsten Einträge an das
LLM geschickt.
Ohne RAG umfasst der Prompt mehr als 600 000 Tokens; mit RAG genügen rund 10 000.

## 4. Frontend

`calculator.js` und `index.html` bilden die Hauptoberfläche. Die Texte der Benutzeroberfläche werden aus `translations.json` geladen. Über `/api/analyze-billing` wird die Berechnung gestartet. `quality.js` bedient die Testseite `quality.html` und ruft `/api/quality` auf.

## 5. Tests und Qualitätssicherung

Die wichtigsten Tests liegen im Verzeichnis `tests/` und prüfen sowohl API‑Endpunkte als auch die Pauschalenlogik. Zusätzlich existiert `run_quality_tests.py`, das Beispieltexte gegen erwartete Baseline‑Ergebnisse vergleicht. Die Tests können mit

```bash
pytest
```

ausgeführt werden.

## 6. Daten und Konfiguration

Im Ordner `data/` liegen sämtliche JSON‑Dateien für Leistungskatalog, TARDOC‑Informationen und Pauschalen. Grosse Dateien werden über Git LFS versioniert. Ein API‑Key für Google Gemini wird in einer `.env`‑Datei hinterlegt (`GEMINI_API_KEY`). Weitere optionale Variablen (`GITHUB_TOKEN`, `GITHUB_REPO`) ermöglichen die automatische Erstellung von Feedback‑Issues.

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
