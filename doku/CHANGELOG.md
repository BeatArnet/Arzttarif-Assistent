# Changelog

Alle nennenswerten Änderungen dieses Projekts.

## Versionsübersicht

### V4.3 (2025-11-24, aktuell)
- Design neu zweispaltig und damit für breitere Bildschirme
geeignet.

### V4.2 (2025-11-22)
- Pauschalen-Engine überarbeitet: strukturierte UND/ODER-Prüfung nutzt vorberechnete Indizes, zählt LKN-Treffer und priorisiert spezifische Codes vor C9x-Fallbacks; irrelevante Tabellen (z. B. OR/ANAST) werden für Erklärungen gefiltert, Gruppen-Vergleiche heben Unterschiede pro Suffix hervor, potenzielle ICDs werden mitgeliefert; neue Konfiguration `REGELPRUEFUNG.pauschale_explanation_excluded_lkn_tables`.
- Frontend & API: Pauschalen-Bedingungen lassen sich aus der Ergebnisliste heraus anklicken; Details werden bei Bedarf über `/api/pauschale-conditions-html` mit dem gespeicherten Kontext nachgerendert und serverseitig via `bleach` bereinigt; Status-Pills und Taxpunkt-Differenzen erleichtern den Vergleich alternativer Pauschalen.
- UX: Fortschrittsanzeige mit animiertem „Flying Doctor“-Overlay für laufende Analysen, stabilere Busy/Spinner-States und sanftere Modal-Navigation; Pauschalen-Details und Erklärungen bleiben nachladbar, ohne den Hauptlauf neu zu starten.
- Daten & Tests: Tarif- und Synonymdaten (LKAAT, TARDOC, Pauschalen*, CHOP, DIGNITAETEN, synonyms.json, baseline/beispiele/vektor_index_codes) aktualisiert; neue Tests decken Pauschalen-Selektion/Erklärungen, ICD/CHOP-Endpunkte, Synonym-Pipeline und Stage-1-Kontext ab; `requirements.txt` um `bleach` ergänzt.

### V4.1 (2025-11-03)
- Brick-Quiz als optionales Trainingsmodul integriert: neue Seite `/brick_quiz`, Feature-Flag `FEATURES.brick_quiz_enabled` in `config.ini`, statische Auslieferung über `server.py`; Button samt Übersetzungen direkt aus `/api/version` gesteuert.
- Navigationsleiste überarbeitet: Feedback, PDF-Export und Qualitätskontrolle liegen nun im Hamburger-Menü; Brick-Quiz-Schalter sitzt neben der Sprachauswahl und lokalisiert sich unmittelbar beim Sprachwechsel.
- Frontend-Polish: Styles des Brick-Quiz an das bestehende UI angepasst (Pill-Buttons, Overlays, Blur-Dropdowns) und kleinere Layout-Korrekturen (Menü-Schattierung, Sicherheit beim Öffnen neuer Tabs).
- Dokumentation und Konfiguration auf Version 4.1 / 03.11.2025 aktualisiert.

### V4.0  (2025-10-31)
- Optimierter Code zur beschleunigten Validierung von Pauschalen

### V3.9 (2025-10-30)
- GUI passt auf eine normale Bildschirmseite (vertikale Abstände der einzelnen Elemente reduziert)
- Ausgabe kann als PDF gespeichert bzw. gedruckt werden

### V3.8 (2025-10-29)
- Backend/Regelprüfung: Pauschalen-Erklärungen zeigen nur noch Kandidaten mit relevanten LKN-Beispielen; Ausschlusstabellen sind via `config.ini` steuerbar, generische C9x-Fallbacks bleiben erhalten. Listenbedingungen akzeptieren nun Medikationsangaben und neue LKN-Tabellentypen.
- LLM-Kontext & Prompts: Variantenbildung filtert aggressive Stopwörter, koppelt Synonyme enger an reale Nutzereingaben und verhindert doppelte Katalogtitel; Stage-1-Instruktionen analysieren sorgfältig, wenn Beratungsminuten genannt werden.
- Frontend: Fortschrittsanzeige arbeitet mit animierten Phasen statt Logliste und ist in DE/FR/IT textlich abgestimmt; Info-Chips (LKN, ICD, Medikamente) nutzen einheitliches Pillen-Design mit Overlays für Medikamentendetails.
- Tools & Konfiguration: Synonym-GUI lädt und speichert Laufzeitpräferenzen (Fenstergeometrie, Dateipfade) in `config.runtime.json`, ohne `config.ini` zu überschreiben; Defaults für LLM-Provider der Synonym-Generierung korrigiert.
- Daten & Tests: Synonym-, Beispiel- und Baseline-Daten aktualisiert; neue Tests decken den LKN-Filter in der Pauschalenlogik sowie die bereinigten Prompt-Varianten ab. Qalitätssicherung: 98-100% korrekt bei Gesamttokenzahl <1 Mio

### V3.6 (2025-10-21)
- ICD-Suche überarbeitet: neues Dropdown mit Tastatursteuerung, optionalem „nur passende Diagnosen“-Modus und persistenter Nutzerpräferenz; Treffer lassen sich dadurch zielgerichtet einschränken.
- Checkbox „ICD berücksichtigen“ merkt sich den eigenen Zustand und wird nur noch an das Backend gesendet, wenn tatsächlich Codes eingetragen sind – das verhindert, dass Pauschalen ohne ICD-Kontext voreilig verworfen werden.
- Medikamente/GTIN lassen sich als Freitextliste eingeben; das Backend löst die Angaben automatisch in ATC-Codes auf und stellt sie Regellogik wie Pauschalen-Checks zur Verfügung.
- Pauschalen-Details zeigen jetzt direkt, welche ICD- bzw. LKN-Anforderungen durch den gelieferten Kontext erfüllt wurden, inklusive anklickbarer Verlinkungen für schnelle Nachvollziehbarkeit.
- Das GUI wurde komplett überarbeitet und es wird neu mit Pop-ups gearbeitet.
- Die Prüflogik wird semi-grafisch dargestellt und kann jetzt auch verschachtelte Bedingungen anzeigen. 

### V3.5 (2025-10-18)
- Pauschalen-Orchestrator liefert pro Kandidat eine aufbereitete Trefferanalyse (ICD-, LKN-, Mengen- und Kontexttreffer) zurück, sodass die UI klar markieren kann, warum eine Bedingung erfüllt wurde.
- Feedback-Dialog reichert Meldungen automatisch mit Nutzerinput, Analyseergebnis und Browserkontext an und spart damit die manuelle Nachdokumentation bei Rückmeldungen.

### V3.4 (2025-10-10)
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
- Favicon-Auslieferung behoben (Chrome/Render): Whitelist der statischen Dateien in server.py erweitert; Favicon-Links in index.html auf absolute Pfade mit sizes umgestellt.
- DX-Fix: Pylance-Warnung zu datetime durch Modul-Alias (import datetime as dt) gelöst.
- Keine Änderungen an der Abrechnungs-/Regellogik.

### V3.3 (2025-10-09)
- Neues, responsives GUI-Layout: breitere TARDOC-Tabelle, verbesserte Spaltenbreiten und Abstände, Layout passt sich dem Viewport an.
- Hinweis-/Kommentarspalte verbreitert, Eingabefeld-Gestaltung verfeinert; diverse Darstellungsfehler (Umlaute, Farben) korrigiert.
- Fokus auf Usability und Lesbarkeit; keine fachlichen Logikänderungen.
- Neues, responsives GUI‑Layout (breitere TARDOC‑Tabelle, verbesserte Spaltenbreiten/Abstände, Viewport‑Anpassung)
- Hinweisspalte verbreitert, Eingabefeld‑Darstellung verfeinert, diverse Anzeige‑Korrekturen (Umlaute/Farben)
- Fokus auf Usability; keine Änderungen an der Abrechnungs‑Logik
- Ordner- und Dateistruktur übersichtlicher gestaltet 

### V3.2 (2025-10-06)
- Synonym‑Subsystem neu strukturiert: LKN‑basierter Katalog mit m:n‑Zuordnungen; abwärtskompatibel
- Regelprüfung: striktere Kumulationsregeln; Medikamentenprüfung primär via ATC (optional GTIN/Bezeichnung)
- Prompts (DE/FR/IT) gehärtet; Korrektur beim Trimmen des Stage‑2‑Kontexts
- Logging‑Korrekturen; Temperatur pro Modell via `config.ini` konfigurierbar
- Erweiterte QS‑Tests; fehlerhafte Warnungen behoben
- Synonym-Subsystem neu strukturiert: Katalog basiert nun auf LKN und erlaubt m:n-Zuordnungen; bestehende Dateien bleiben kompatibel.
- Verbesserte Regelprüfung: strikteres Einhalten von Kumulationsregeln bei Einzelleistungen; Medikamentenprüfung primär via ATC-Code (optional GTIN/Bezeichnung).
- Prompts überarbeitet und gehärtet (DE/FR/IT); Korrektur beim Trimmen des Stage-2-Kontexts.
- Logging: kleinere Korrekturen; Temperatur pro Modell in config.ini konfigurierbar; erweiterte Qualitätstests.
- Qualitätssicherung: Tests ergänzt, fehlerhafte Warnungen behoben, QS-Szenarien beantworten nun konsistenter.

### V3.1 (2025-09-29)
- Suche/Ranking: tokenbasierte Pauschalen‑Suche, allgemeiner Keyword‑Filter; erneuter LKN‑Suchlauf bei Nulltreffern
- Konsistentere Algorithmen für LKN‑Erkennung
- `analyze_billing` refaktoriert; robustere Request‑Typisierung und Guards
- Granulare Logging‑Konfiguration ([LOGGING])
- Feintuning: getrennte Temperaturen pro Stufe/Sub‑Task (z. B. `stage2_mapping_temperature`, `stage2_ranking_temperature`)
- Suche und Ranking: tokenbasierte Suche für Pauschalen, allgemeiner Keyword-Filter; erneuter LKN-Suchlauf bei Nulltreffern; konsistentere Algorithmen.
- Codequalität: Analyze_billing refaktoriert (geringere Komplexität); robustere Typisierungen und Request-Guards.
- Logging: granulare Logging-Konfiguration eingeführt (feiner steuerbar per [LOGGING]).
- Feintuning LLM: getrennte Temperatur-Parameter pro Stufe und Sub-Task (z. B. stage2_mapping_temperature, stage2_ranking_temperature).

### V3.0 (2025-09-22)
- Mehrere LLM-Provider konfigurierbar (Gemini, OpenAI, SwissAI/Apertus, Ollama-kompatibel) pro Stufe (Stage 1/2) via config.ini und Umgebungsvariablen.
- OpenAI-kompatible Einbindung von Apertus (PublicAI) inkl. anpassbarer *_BASE_URL und Token-Budgets.
- Konfigurierbares Prompt-Trimming zur Einhaltung von Tokenbudgets:
  - Apertus: automatisches Kürzen des Kontexts gemäss [OPENAI] trim_*.
  - Gemini: optionales Trimmen gemäss [GEMINI].
- Feinsteuerung des Kontexts über [CONTEXT] in config.ini (z. B. include_*, max_context_items, Force_include_codes).
- Synonym-Editor stabilisiert (python -m synonyms), zusätzliche Optionen in [SYNONYMS] (Fenstergeometrie/Spaltenbreiten); das Katalogformat unterstützt jetzt lkns für Mehrfachzuordnungen und bleibt mit bestehenden lkn-Einträgen kompatibel.
- Erweiterte Logging-Optionen und Rotations-Logging ([LOGGING]), optional Rohantworten.
- Regelprüfung: Option kumulation_explizit zur strikteren Kumulationslogik.
- Standardkonfiguration aktualisiert (Version 3.0, Tarif 1.1c).

### V2.8 (2025-08-12)
- Synonymverwaltung mit GUI, konfigurierbar in config.ini. Unterstützt den Vergleich der aktuellen zur neuen Tarifversion (farblich markierte Einträge für neue, gelöschte und geänderte LKNs).
- Vergleich verschiedener LLM-Provider und Modelle über llm_vergleich.py, inklusive unterschiedliche Provider und Modelle.
- RAG-Modus nutzt Embeddings zur massiven Tokenreduktion (Faktor 10) in Kombination mit der Synonymliste, sodass nahezu kein Qualitätsverlust entsteht.
- Aktualisiert auf Tarifversion 1.1c der OAAT-OTMA AG (Stand 08.08.2025).

### V2.7 (2025-08-04)
- Erweiterte Logging-Optionen: Granulare Steuerung der LLM-Zwischenschritte über config.ini.
- Erkennt einmalig fehlende 	emperature-Unterstützung von Modellen und speichert dies in config.ini.

### V2.6
- Optionaler RAG-Modus über config.ini schaltbar.
- Versionsnummer ebenfalls in config.ini definiert und in der Oberfläche angezeigt.
- Reduziert die Grösse des LLM-Kontexts: mit RAG werden nur rund 10 000 Tokens übertragen, ohne RAG über 600 000.

### V2.5 (2025-07-24)
- Einheitliches Übersetzungssystem: Alle UI-Texte liegen jetzt zentral in 	ranslations.json.
- Die Übersetzungsfunktionen sind direkt in calculator.js und quality.js eingebaut.
- Sämtliche Oberflächenelemente werden darüber dynamisch lokalisiert.
- Der Hinweis, keine persönlichen Daten einzugeben, ist nun deutlich sichtbar.

### V2.4 (2025-07-21)
- Neuer CHOP-Lookup: /api/chop?q=<term> liefert passende Codes mit Kurzbeschreibung.
- Kleine Beispieldatei CHOP_Katalog.json hinzugefügt.
- GUI erweitert um CHOP-Suche. Gewählter Code wird beim Verlassen des Feldes automatisch in das Formular übernommen.
- ICD-Codes lassen sich jetzt über ein dynamisches Dropdown suchen und übernehmen.
- Verbesserte LKN-Erkennung unterstützt gemischte Formate wie ANN.AA.NNNN.
- Einheitliches Layout: Dropdown-Pfeile sind klickbar und Modalfenster lassen sich am Kopf verschieben.

### V2.3
- Überarbeitetes Feedback-Modul mit modalem Formular und Kontextinformationen.
- In der Pilotphase werden alle Rückmeldungen im Repository [BeatArnet/Arzttarif_Assistent_dev](https://github.com/BeatArnet/Arzttarif_Assistent_dev) gesammelt.

### V2.2
- Dokumentation (README.md, INSTALLATION.md) aktualisiert mit den neuesten Hinweisen und Versionsdetails.
- Neue Feedback-Funktion: Über ein Formular kann Feedback an ein GitHub-Repository gesendet oder lokal gespeichert werden, wenn keine GitHub-Konfiguration vorliegt.

### V2.0
- **Qualitätstests und Baseline-Vergleiche:** Einführung einer neuen Testseite (quality.html, quality.js) und eines Skripts (
un_quality_tests.py) zum automatisierten Vergleich von Beispielen mit Referenzwerten (Baseline_results.json). Ein neuer Backend-Endpunkt /api/quality wurde dafür in server.py hinzugefügt.
- **Erweiterte Pop-up-Funktionen:** Pop-up-Fenster im Frontend sind nun verschiebbar und in der Grösse anpassbar (calculator.js).
- **Verbesserte Pauschalenlogik:** Die Auswertung strukturierter Pauschalenbedingungen erfolgt nun über den Orchestrator evaluate_pauschale_logic_orchestrator in 
egelpruefer_pauschale.py, begleitet von neuen Unittests.
- **Daten- und Funktionsumfang:** Zusätzliche Datendateien wie DIGNITAETEN.json wurden integriert. Die TARDOC-Daten wurden in TARDOC_Tarifpositionen.json und TARDOC_Interpretationen.json aufgeteilt.
- **Verbesserte Textaufbereitung:** Neue Hilfsfunktionen in utils.py zur Erweiterung von Komposita (expand_compound_words) und zur Synonym-Erkennung (SYNONYM_MAP).
- **Ausgelagerte Prompts:** Die Prompt-Definitionen für die KI wurden in die separate Datei prompts.py ausgelagert und unterstützen Mehrsprachigkeit.
- **Test-Endpoint /api/test-example:** Über diesen Endpunkt lassen sich Beispiele gegen die erwarteten Ergebnisse in Baseline_results.json prüfen (siehe quality.html).

### V1.1
- JSON-Datendateien wurden umbenannt und der ehemals kombinierte TARDOC-Datensatz in **TARDOC_Tarifpositionen.json** und **TARDOC_Interpretationen.json** aufgeteilt.
- Alte Dateinamen wie 	blLeistungskatalog.json, 	blPauschaleLeistungsposition.json oder 	blTabellen.json heissen nun entsprechend LKAAT_Leistungskatalog.json, PAUSCHALEN_Leistungspositionen.json und PAUSCHALEN_Tabellen.json.
- server.py sowie das README verwenden diese neuen Namen; index.html weist nun die Version "V1.1" aus.
- utils.py bietet ein Übersetzungssystem für Regelmeldungen und Condition-Typen in Deutsch, Französisch und Italienisch.
- In 
egelpruefer_pauschale.py sorgt eine Operator-Präzedenzlogik für korrektes "UND vor ODER" bei strukturierten Bedingungen.
- evaluate_structured_conditions unterstützt einen konfigurierbaren GruppenOperator (Standard UND).
- Die mehrsprachigen Prompts für LLM Stufe 1 und Stufe wurden in prompts.py ausgelagert.
- Funktionale Erweiterungen: interaktive Info-Pop-ups, mehrsprachige Oberfläche, erweiterte Suchhilfen, Fallback-Logik für Pauschalen, mobile Ansicht, zusätzliche Beispieldaten sowie Korrekturen bei Mengenbegrenzungen und ICD-Verarbeitung.

### V1.0 (2025-06-17)
- Erste lauffähige Version des Prototyps.
