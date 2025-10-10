# Changelog

Alle nennenswerten Änderungen dieses Projekts.

## [3.4] – 2025-10-10
- Favicon-Auslieferung korrigiert: Catch-all-Whitelist in `server.py` erweitert
  (u. a. `favicon-32.png`, `favicon.ico`, `robots.txt`), Favicon-Links in
  `index.html` auf absolute Pfade mit `sizes` umgestellt. Behebt 404 in Chrome
  und auf Render.
- Entwicklerfreundlichkeit: Pylance-Warnung „Class definition for \"datetime\"
  depends on itself“ bereinigt durch expliziten Modul-Alias
  (`import datetime as dt`). Kein Laufzeitverhalten geändert.
- Dokumentation aktualisiert (README/INSTALLATION/DEVELOPMENT) und
  `config.ini` auf Version 3.4 gesetzt.
- Keine Änderungen an Abrechnungs‑/Regel‑Logik.

## [3.3] – 2025-10-09
- Neues, responsives GUI‑Layout (breitere TARDOC‑Tabelle, verbesserte Spaltenbreiten/Abstände, Viewport‑Anpassung)
- Hinweisspalte verbreitert, Eingabefeld‑Darstellung verfeinert, diverse Anzeige‑Korrekturen (Umlaute/Farben)
- Fokus auf Usability; keine Änderungen an der Abrechnungs‑Logik
- Ordner- und Dateistruktur übersichtlicher gestaltet 

## [3.2] – 2025-10-06
- Synonym‑Subsystem neu strukturiert: LKN‑basierter Katalog mit m:n‑Zuordnungen; abwärtskompatibel
- Regelprüfung: striktere Kumulationsregeln; Medikamentenprüfung primär via ATC (optional GTIN/Bezeichnung)
- Prompts (DE/FR/IT) gehärtet; Korrektur beim Trimmen des Stage‑2‑Kontexts
- Logging‑Korrekturen; Temperatur pro Modell via `config.ini` konfigurierbar
- Erweiterte QS‑Tests; fehlerhafte Warnungen behoben

## [3.1] – 2025-09-29
- Suche/Ranking: tokenbasierte Pauschalen‑Suche, allgemeiner Keyword‑Filter; erneuter LKN‑Suchlauf bei Nulltreffern
- Konsistentere Algorithmen für LKN‑Erkennung
- `analyze_billing` refaktoriert; robustere Request‑Typisierung und Guards
- Granulare Logging‑Konfiguration ([LOGGING])
- Feintuning: getrennte Temperaturen pro Stufe/Sub‑Task (z. B. `stage2_mapping_temperature`, `stage2_ranking_temperature`)

## [3.0] – 2025-09-22
- Mehrere LLM‑Provider pro Stufe (Gemini, OpenAI, Apertus, Ollama‑kompatibel)
- Prompt‑Trimming und Kontext‑Steuerung (`[OPENAI]`, `[GEMINI]`, `[CONTEXT]`)
- Synonym‑Editor stabilisiert; Katalog unterstützt `lkns` (Mehrfachzuordnung)
- Erweiterte Logging‑Optionen (Rotations‑Logging); Regelprüfung `kumulation_explizit`
- Tarifbasis: OAAT‑OTMA AG, Tarifversion 1.1c (08.08.2025)
