# Arzttarif-Assistent

Dies ist ein Prototyp einer Webanwendung zur Unterstützung bei der Abrechnung medizinischer Leistungen nach dem neuen Schweizer Arzttarif (TARDOC und Pauschalen). Die Anwendung nimmt eine Freitextbeschreibung einer medizinischen Leistung entgegen und schlägt die optimale Abrechnungsart (Pauschale oder TARDOC-Einzelleistung) vor. Sie kombiniert eine KI-basierte Leistungsidentifikation mit detaillierter lokaler Regel- und Bedingungsprüfung.

## Wichtige Hinweise

*   **Ohne Gewähr:** Der Arzttarif-Assistent ist eine Open-Source-Anwendung und ein Prototyp. Die Ergebnisse können Fehler enthalten und sind nicht verbindlich.
*   **Offizielle Quellen:**
    *   Für verbindliche Tarifinformationen und zur Überprüfung der Resultate konsultieren Sie bitte den offiziellen **OAAT Tarifbrowser**: [https://tarifbrowser.oaat-otma.ch/startPortal](https://tarifbrowser.oaat-otma.ch/startPortal)
    *   Die Ärzteschaft kann sich zudem auf der **Tarifplattform der FMH** orientieren: [https://www.tarifeambulant.fmh.ch/](https://www.tarifeambulant.fmh.ch/)
*   **Open Source:** Das Projekt ist öffentlich auf GitHub verfügbar: [https://github.com/BeatArnet/Arzttarif-Assistent](https://github.com/BeatArnet/Arzttarif-Assistent)
*   Keine persönlichen Daten eingeben – KI-Abfragen laufen über externe LLM‑Dienste (z. B. Gemini, OpenAI, SwissAI/Apertus, Ollama‑Gateway).
*   **Tarifbasis:** OAAT‑OTMA AG, Tarifversion 1.1c vom 08.08.2025.

## Versionsübersicht

### V3.0 (Aktuell)
- Mehrere LLM‑Provider konfigurierbar (Gemini, OpenAI, SwissAI/Apertus, Ollama‑kompatibel) pro Stufe (Stage 1/2) via `config.ini` und Umgebungsvariablen.
- OpenAI‑kompatible Einbindung von Apertus (PublicAI) inkl. anpassbarer `*_BASE_URL` und Token‑Budgets.
- Konfigurierbares Prompt‑Trimming zur Einhaltung von Tokenbudgets:
  - Apertus: automatisches Kürzen des Kontexts gemäss `[OPENAI] trim_*`.
  - Gemini: optionales Trimmen gemäss `[GEMINI]`.
- Feinsteuerung des Kontexts über `[CONTEXT]` in `config.ini` (z. B. `include_*`, `max_context_items`, `force_include_codes`).
- Synonym‑Editor stabilisiert (`python -m synonyms`), zusätzliche Optionen in `[SYNONYMS]` (Fenstergeometrie/Spaltenbreiten); Katalogformat mit `lkn` und sprachgetrennten Listen bleibt kompatibel.
- Erweiterte Logging‑Optionen und Rotations‑Logging (`[LOGGING]`), optional Rohantworten.
- Regelprüfung: Option `kumulation_explizit` zur strikteren Kumulationslogik.
- Standardkonfiguration aktualisiert (Version 3.0, Tarif 1.1c).

### V2.8
- Synonymverwaltung mit GUI, konfigurierbar in `config.ini`. 
  Synonymverwaltung unterstützt beim Vergleich der aktuellen zur neuen Tarifversion 
  (farblich markierte Eintragungen für neue, gelöscht und geänderte LKNs).)
- Vergleich verschiedener LLM‑Provider und Modelle über `llm_vergleich.py`, inklusive unterschiedliche Provider und Modelle.
- RAG‑Modus nutzt Embeddings zur massiven Tokenreduktion (Faktor 10) in Kombination mit der Synonymtabelle, so dass (fast) kein Qualitätsverlust entsteht.
- Aktualisiert auf Tarifversion 1.1c der OAAT‑OTMA AG (Stand 08.08.2025).

### V2.7
- Erweiterte Logging-Optionen: Granulare Steuerung der LLM-Zwischenschritte über `config.ini`.
- Erkennt einmalig fehlende `temperature`-Unterstützung von Modellen und speichert dies in `config.ini`.

### V2.6
- Optionaler RAG-Modus über `config.ini` schaltbar.
- Versionsnummer ebenfalls in `config.ini` definiert und in der Oberfläche angezeigt.
- Reduziert die Grösse des LLM-Kontexts: mit RAG werden nur rund 10 000 Tokens übertragen, ohne RAG sind es über 600 000.

### V2.5
- Einheitliches Übersetzungssystem: Alle UI-Texte liegen jetzt zentral in `translations.json`.
- Die Übersetzungsfunktionen sind direkt in `calculator.js` und `quality.js` eingebaut.
- Sämtliche Oberflächenelemente werden darüber dynamisch lokalisiert.
- Der Hinweis, keine persönlichen Daten einzugeben, ist nun deutlich sichtbar.

### V2.4
- Neuer CHOP‑Lookup: `/api/chop?q=<term>` liefert passende Codes mit Kurzbeschreibung.
- Kleine Beispieldatei `CHOP_Katalog.json` hinzugefügt.
- GUI erweitert um CHOP-Suche. Gewählter Code wird beim Verlassen des Feldes automatisch in das Formular übernommen.
- ICD-Codes lassen sich jetzt über ein dynamisches Dropdown suchen und übernehmen.
- Verbesserte LKN-Erkennung unterstützt gemischte Formate wie `ANN.AA.NNNN`.
- Einheitliches Layout: Dropdown-Pfeile sind klickbar und Modalfenster lassen sich am Kopf verschieben.

### V2.3
- Überarbeitetes Feedback-Modul mit modalem Formular und Kontextinformationen.
- In der Pilotphase werden alle Rückmeldungen im Repository
  [BeatArnet/Arzttarif_Assistent_dev](https://github.com/BeatArnet/Arzttarif_Assistent_dev)
  gesammelt.

### V2.2
- Dokumentation (README.md, INSTALLATION.md) aktualisiert mit den neuesten Hinweisen und Versionsdetails.
- Neue Feedback-Funktion: Über ein Formular kann Feedback an ein GitHub-Repository gesendet oder lokal gespeichert werden, wenn keine GitHub-Konfiguration vorliegt.

### V2.0
- **Qualitätstests und Baseline-Vergleiche:** Einführung einer neuen Testseite (`quality.html`, `quality.js`) und eines Skripts (`run_quality_tests.py`) zum automatisierten Vergleich von Beispielen mit Referenzwerten (`baseline_results.json`). Ein neuer Backend-Endpunkt `/api/quality` wurde dafür in `server.py` hinzugefügt.
- **Erweiterte Pop-up-Funktionen:** Pop-up-Fenster im Frontend sind nun verschiebbar und in der Grösse anpassbar (`calculator.js`).
- **Verbesserte Pauschalenlogik:** Die Auswertung strukturierter Pauschalenbedingungen erfolgt nun über den Orchestrator `evaluate_pauschale_logic_orchestrator` in `regelpruefer_pauschale.py`, begleitet von neuen Unittests.
- **Daten- und Funktionsumfang:** Zusätzliche Datendateien wie `DIGNITAETEN.json` wurden integriert. Die TARDOC-Daten wurden in `TARDOC_Tarifpositionen.json` und `TARDOC_Interpretationen.json` aufgeteilt.
- **Verbesserte Textaufbereitung:** Neue Hilfsfunktionen in `utils.py` zur Erweiterung von Komposita (`expand_compound_words`) und zur Synonym-Erkennung (`SYNONYM_MAP`).
- **Ausgelagerte Prompts:** Die Prompt-Definitionen für die KI wurden in die separate Datei `prompts.py` ausgelagert und unterstützen Mehrsprachigkeit.
- **Test-Endpoint `/api/test-example`:** Über diesen Endpunkt lassen sich Beispiele gegen die erwarteten Ergebnisse in `baseline_results.json` prüfen (siehe `quality.html`).

### V1.1
- JSON-Datendateien wurden umbenannt und der ehemals kombinierte TARDOC-Datensatz in **TARDOC_Tarifpositionen.json** und **TARDOC_Interpretationen.json** aufgeteilt.
- Alte Dateinamen wie `tblLeistungskatalog.json`, `tblPauschaleLeistungsposition.json` oder `tblTabellen.json` heissen nun entsprechend `LKAAT_Leistungskatalog.json`, `PAUSCHALEN_Leistungspositionen.json` und `PAUSCHALEN_Tabellen.json`.
- `server.py` sowie das README verwenden diese neuen Namen; `index.html` weist nun die Version "V1.1" aus.
- `utils.py` bietet ein Übersetzungssystem für Regelmeldungen und Condition-Typen in Deutsch, Französisch und Italienisch.
- In `regelpruefer_pauschale.py` sorgt eine Operator-Präzedenzlogik für korrektes "UND vor ODER" bei strukturierten Bedingungen.
- `evaluate_structured_conditions` unterstützt einen konfigurierbaren `GruppenOperator` (Standard `UND`).
- Die mehrsprachigen Prompts für LLM Stufe 1 und Stufe wurden in `prompts.py` ausgelagert.
- Funktionale Erweiterungen: interaktive Info-Pop-ups, mehrsprachige Oberfläche, erweiterte Suchhilfen, Fallback-Logik für Pauschalen, mobile Ansicht, zusätzliche Beispieldaten sowie Korrekturen bei Mengenbegrenzungen und ICD-Verarbeitung.

### V1.0
- Erste lauffähige Version des Prototyps.

## Beschreibung

Der Assistent analysiert die eingegebene Leistungsbeschreibung mithilfe eines Large Language Models (Google Gemini), um relevante Leistungspositionen (LKNs) zu identifizieren. Ein Backend-Regelwerk prüft die Konformität dieser LKNs (Mengen, Kumulationen etc.). Die Kernlogik entscheidet dann, ob eine Pauschale für die (regelkonformen) Leistungen anwendbar ist. Falls ja, wird die passendste Pauschale ausgewählt und deren Bedingungen detailliert geprüft. Falls keine Pauschale greift, wird eine Abrechnung nach TARDOC-Einzelleistungen vorbereitet.

Das Frontend zeigt das Ergebnis übersichtlich an, mit Details zur initialen KI-Analyse, der Regelprüfung und zur finalen Abrechnungsempfehlung (inklusive Pauschalenbegründung und detaillierter Bedingungsprüfung).

## Mehrsprachigkeit

Der Assistent ist in den drei Landessprachen DE, FR und IT verfügbar. Die Sprache richtet sich nach der Browsereinstellung, sie kann aber auch manuell geändert werden. Allerdings sollte man die Seite dann neu aufrufen, damit alles neu initialisiert wird. Es zeigt sich, dass die Antworten der KI nicht in allen drei Sprachen gleich (gut) funktioniert. An der Konsistenz der Antworten muss noch gearbeitet werden.

## Übersetzen von Texten

Alle Beschriftungen und Meldungen der Benutzeroberfläche liegen zentral in der Datei `translations.json`. Diese enthält die deutschen Texte sowie Übersetzungen in Französisch und Italienisch. Die Dateien `calculator.js` und `quality.js` laden diese Datei über `loadTranslations()` und stellen mit `t(key, lang)` eine einfache Lookup-Funktion bereit. Neue Texte müssen nur in `translations.json` ergänzt werden.

## Kernlogik / Architektur

1.  **Frontend (`index.html`, `calculator.js`):**
    *   Nimmt Benutzereingaben (Text, optionale ICDs, GTINs, Kontext wie Alter/Geschlecht) entgegen.
    *   Sendet die Anfrage an das Backend.
    *   Empfängt das strukturierte Ergebnis vom Backend.
    *   Stellt die Ergebnisse benutzerfreundlich dar.

2.  **Backend (Python/Flask - `server.py`):**
    *   Empfängt Anfragen vom Frontend.
    *   **LLM Stufe 1 (`call_gemini_stage1`):** Identifiziert LKNs und extrahiert Kontext aus dem Benutzertest mithilfe von Google Gemini.
    *   **Regelprüfung LKN (`regelpruefer_einzelleistungen.py`):** Prüft die identifizierten LKNs auf Konformität mit TARDOC-Regeln.
    *   **Pauschalen-Anwendbarkeitsprüfung (`regelpruefer_pauschale.py`):** Identifiziert und prüft potenzielle Pauschalen.
    *   **Entscheidung & TARDOC-Vorbereitung:** Entscheidet "Pauschale vor TARDOC".
    *   Sendet das Gesamtergebnis zurück an das Frontend.

3.  **Daten (`./data` Verzeichnis):**
    *   Die JSON-Datendateien (`LKAAT_Leistungskatalog.json`, `PAUSCHALEN_*.json`, `TARDOC_*.json` etc.) dienen als lokale Wissensbasis.
    *   **Wichtiger Hinweis:** Die JSON-Dateien werden direkt und ohne Umwege in diesem GitHub-Repository gespeichert und versioniert. Für grosse Dateien wird Git LFS verwendet.

## Technologie-Stack

*   **Backend:** Python 3, Flask, Gunicorn (für Produktion)
*   **Frontend:** HTML5, CSS3, Vanilla JavaScript
*   **KI-Service:** Google Gemini API (via REST)
*   **Daten:** JSON (gespeichert in Git LFS)

## Setup und Installation (Lokal)

1.  **Voraussetzungen:**
    *   Python (z.B. 3.11.x)
    *   `pip` (Python Package Installer)
    *   Git
    *   Git LFS ([https://git-lfs.com](https://git-lfs.com))
2.  **Repository klonen:**
    ```bash
    git clone https://github.com/BeatArnet/Arzttarif-Assistent.git
    cd Arzttarif-Assistent
    ```
3.  **Virtuelle Umgebung (Empfohlen):**
    ```bash
    python -m venv venv
    # Windows:
    venv\Scripts\activate
    # macOS/Linux:
    source venv/bin/activate
    ```
4.  **Abhängigkeiten installieren:**
    ```bash
    pip install -r requirements.txt
    ```
5.  **API-Schlüssel konfigurieren:**
    *   Erstelle eine Datei namens `.env` im Hauptverzeichnis.
    *   Hinterlege die notwendigen Schlüssel abhängig vom gewählten Provider (nur die benötigten setzen):
        ```env
        # LLM-Provider
        GEMINI_API_KEY="..."                 # für Google Gemini
        OPENAI_API_KEY="..."                 # für OpenAI
        APERTUS_API_KEY="..."                # für SwissAI/Apertus (PublicAI)
        APERTUS_BASE_URL="https://api.publicai.co/v1"  # optional
        OLLAMA_BASE_URL="http://localhost:11434/v1"     # optional, OpenAI-kompatibel

        # Synonym-Generator (falls externes LLM gewünscht)
        SYNONYM_LLM_API_KEY="..."
        SYNONYM_LLM_MODEL="gemini-2.5-flash"
        ```
6.  **Anwendung starten:**
    ```bash
    python server.py
    ```
    Öffne `http://127.0.0.1:8000` im Browser.

## Deployment auf Render.com

Die Anwendung kann auf Plattformen wie Render.com deployed werden. Hierfür sind eine `Procfile` und die Konfiguration von Umgebungsvariablen für den API‑Schlüssel des gewählten Providers notwendig (z. B. `APERTUS_API_KEY`, `GEMINI_API_KEY`). Der `Standard`‑Plan (oder höher) wird aufgrund des RAM‑Bedarfs (>512 MB) empfohlen.

### Logs auf Render.com durchsuchen

Im Render-Dashboard kann man die Server-Logs einsehen. Rufe den entsprechenden Service auf und wähle den Reiter **Logs**. Oben rechts lässt sich ein Zeitraum festlegen. Über das Suchfeld kann dann nach `inputText` gesucht werden, um die Anfragen in diesem Zeitraum zu filtern.

## Qualitätstests

Die Datei `data/beispiele.json` enthält Testfälle. Mit `run_quality_tests.py` können diese gegen die erwarteten Ergebnisse in `data/baseline_results.json` geprüft werden:
```bash
python run_quality_tests.py
```

## Feedback

Über den Button "Feedback geben" oben neben der Sprachauswahl öffnet sich ein modales Formular.
Es sammelt automatisch Kontextinformationen (URL, Browser, Bildschirmauflösung
sowie eine Momentaufnahme der aktuellen Formulareingaben und Analyseergebnisse)
und sendet sie zusammen mit der Nachricht an das Backend.
Sind `GITHUB_TOKEN` und `GITHUB_REPO` gesetzt, wird daraus ein GitHub-Issue erstellt,
ansonsten landet das Feedback in `feedback_local.json`.
Während der Pilotphase werden alle eingehenden Meldungen im Repository
[BeatArnet/Arzttarif_Assistent_dev](https://github.com/BeatArnet/Arzttarif_Assistent_dev)
gebündelt.

## RAG-Modus und Embeddings generieren

Der optionale RAG-Modus reduziert den Tokenbedarf, indem nur die
relevantesten Katalogeinträge per Vektor-Suche an das LLM gesendet werden.
Die dafür benötigten Embeddings des Leistungskatalogs werden mit dem Skript
`generate_embeddings.py` erzeugt:

```bash
python generate_embeddings.py
```

Das Skript benötigt die Bibliothek `sentence-transformers` und schreibt die Datei
`data/leistungskatalog_embeddings.json`, die vom Server automatisch geladen wird.
Um RAG zu aktivieren, setze in `config.ini` den Wert `enabled = 1` unter
`[RAG]` und stelle sicher, dass die Embedding-Datei vorhanden ist. Führe das
Skript nach Datenänderungen erneut aus.

## Synonym-Subsystem

Um auch umgangssprachliche Begriffe korrekt zu erkennen, besitzt der Assistent
ein optionales Synonym-Subsystem. Es erweitert die bei der
Schlüsselwortextraktion gefundenen Tokens um bekannte Synonyme und erhöht damit
die Trefferquote im Leistungskatalog.

### Synonyme generieren und pflegen

Ein einfaches Tkinter-Werkzeug kann neue Vorschläge aus den vorhandenen
Katalogdaten ableiten. Welcher LLM-Dienst genutzt wird, lässt sich über die
Werte `llm_provider` und `llm_model` im Abschnitt `[SYNONYMS]` der Datei
`config.ini` steuern. Standardmässig wird ein lokaler Ollama‑Server
(`llm_provider = ollama`) mit dem Modell `gpt-oss-20b` angesprochen. Die
Adresse kann über die Umgebungsvariable `OLLAMA_URL` angepasst werden. Für den
Betrieb mit Google Gemini kann `llm_provider = gemini` gesetzt werden.

Bei Verwendung eines externen LLMs muss in der `.env`‑Datei ein
`SYNONYM_LLM_API_KEY` hinterlegt sein und optional `SYNONYM_LLM_MODEL`
gesetzt werden. Für Gemini ist zusätzlich das Paket `google-generativeai`
erforderlich. Ist kein LLM verfügbar, werden keine zusätzlichen Synonyme
erzeugt:

```bash
python -m synonyms
```

Das Fenster zeigt Anzahl und Fortschritt der Anfragen, berechnet die
voraussichtliche Endzeit und erlaubt das Festlegen des Startindex sowie des
Ausgabepfades.

Die Datei `data/synonyms.json` kann anschliessend manuell geprüft und
ergänzt werden. Beim Start des Servers wird sie automatisch eingelesen.
Erfasst der Nutzer einen Begriff aus dieser Liste, wird nun automatisch der
zugehörige Grundbegriff samt Varianten berücksichtigt.

### Aktivierung in der Konfiguration

In `config.ini` kann das Feature unter dem Abschnitt `[Synonyms]` aktiviert
werden:

```ini
[Synonyms]
enabled = 1
catalog_filename = synonyms.json
```

Steht `enabled` auf `0`, nutzt der Assistent ausschliesslich die in
`utils.py` hinterlegte Basismenge `SYNONYM_MAP`.

### Verwendung im System

Der Synonymkatalog wirkt sich an zwei Stellen aus:

1. **Embeddings:** `generate_embeddings.py` lädt `data/synonyms.json` und fügt
   alle Varianten zu den Katalogtexten hinzu, bevor der Vektor berechnet wird.
   So landen auch umgangssprachliche Begriffe in der semantischen Suche.
2. **LLM 1 / Stichwortsuche:** Beim Analysieren der Nutzereingabe erweitert
   `server.py` die Anfrage über `expand_query` um Synonyme. Direkte Treffer
   liefern sofort die hinterlegte LKN, während die Embedding‑Suche den
   unveränderten Ausgangstext verwendet.

### Format `data/synonyms.json`

Der Katalog enthält nun zusätzlich die zugehörige Tarifposition (LKN) und
unterscheidet Synonyme nach Sprache. Jede Position wird über den Grundbegriff
referenziert und speichert ihre Varianten je Sprache unter `synonyms`. Ein
Beispiel:

```json
{
  "Foo": {
    "lkn": "AA.00.0010",
    "synonyms": {
      "de": ["bar"],
      "fr": ["baz"]
    }
  }
}
```

Dieses Format wird vom GUI-Werkzeug erzeugt und von `synonyms.storage`
eingelesen. Vorherige Dateien ohne `lkn`-Feld oder ohne Sprachaufteilung werden
weiterhin unterstützt.

**Hinweis zu den Tokenanforderungen:** Ohne RAG müssen mehr als 600 000 Tokens an
das LLM geschickt werden. Mit RAG reichen etwa 10 000 Tokens für eine typische
Anfrage.

## LLM-Vergleich

Mit `llm_vergleich.py` können verschiedene LLM-Provider und Modelle automatisiert
gegeneinander getestet werden. In `llm_vergleich_results.json` lässt sich für jede
Stufe optional ein eigener Provider samt Modell (`Stage1Provider`/`Stage1Model`
und `Stage2Provider`/`Stage2Model`) definieren; fehlen diese Felder, gelten
`Provider` und `Model` für beide Stufen. Das Skript führt alle Beispiele aus
`data/baseline_results.json` aus und speichert für jedes Modell Korrektheitsrate,
Laufzeit sowie den verbrauchten Tokenumfang.

## Unittests mit `pytest`

Die Python-Tests liegen im Verzeichnis `tests/` und werden mit `pytest` ausgeführt:
```bash
pytest
```

## Urheber

Arnet Konsilium
Beat Arnet
Dr. med., MHA, SW-Ing. HTL/NDS
Wydackerstrasse 41
CH-3052 Zollikofen
[https://what3words.com/apfelkern.gelehrig.konzentration](https://what3words.com/apfelkern.gelehrig.konzentration)
beat.arnet@arkons.ch
P: +41 31 911 32 36
M: +41 79 321 89 36
[www.arkons.ch](https://www.arkons.ch)
