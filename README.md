# Arzttarif-Assistent

Dies ist ein Prototyp einer Webanwendung zur Unterstützung bei der Abrechnung medizinischer Leistungen nach dem neuen Schweizer Arzttarif (TARDOC und Pauschalen). Die Anwendung nimmt eine Freitextbeschreibung einer medizinischen Leistung entgegen und schlägt die optimale Abrechnungsart (Pauschale oder TARDOC-Einzelleistung) vor. Sie kombiniert eine KI-basierte Leistungsidentifikation mit detaillierter lokaler Regel- und Bedingungsprüfung.

## Dokumentation

- Anwenderdokumentation: `doku/DOKU_ANWENDUNG.md`
- Technische Dokumentation: `doku/DOKU_TECHNIK.md`
- Installation/Setup: `doku/INSTALLATION.md`

## Wichtige Hinweise

*   **Ohne Gewähr:** Der Arzttarif-Assistent ist eine Open-Source-Anwendung und ein Prototyp. Die Ergebnisse können Fehler enthalten und sind nicht verbindlich.
*   **Offizielle Quellen:**
    *   Für verbindliche Tarifinformationen und zur Überprüfung der Resultate konsultieren Sie bitte den offiziellen **OAAT Tarifbrowser**: [https://tarifbrowser.oaat-otma.ch/startPortal](https://tarifbrowser.oaat-otma.ch/startPortal)
    *   Die Ärzteschaft kann sich zudem auf der **Tarifplattform der FMH** orientieren: [https://www.tarifeambulant.fmh.ch/](https://www.tarifeambulant.fmh.ch/)
*   **Open Source:** Das Projekt ist öffentlich auf GitHub verfügbar: [https://github.com/BeatArnet/Arzttarif-Assistent](https://github.com/BeatArnet/Arzttarif-Assistent)
*   Keine persönlichen Daten eingeben – KI-Abfragen laufen über externe LLM‑Dienste (z. B. Gemini, OpenAI, SwissAI/Apertus, Ollama‑Gateway).
*   **Tarifbasis:** OAAT‑OTMA AG, Tarifversion 1.1c vom 08.08.2025.

## Versionsübersicht
Die vollständige Versionshistorie befindet sich in `doku/CHANGELOG.md`.

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
    *   Optional vorberechnete Pauschalen-Splits (`PAUSCHALEN_Tabellen_*_map.json`, `Pauschale_cond_table_*`, `lkn_to_tables_*`, `pauschalen_indices_meta.json`) beschleunigen die Kandidatensuche; der Server lädt sie automatisch, sonst werden die Splits zur Laufzeit erzeugt.

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
5.  **Embeddings erzeugen (RAG ist standardmässig aktiviert, `config.ini` `[RAG].enabled = 1`):**
    ```bash
    pip install sentence-transformers
    python generate_embeddings.py
    ```
    Das Skript erzeugt `data/leistungskatalog_embeddings.json`, `data/vektor_index.faiss` und `data/vektor_index_codes.json`. Nach Daten- oder Synonym-Updates erneut ausführen, sonst funktioniert die semantische Suche nicht.
6.  **API-Schlüssel konfigurieren:**
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
7.  **Anwendung starten:**
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

Steht `enabled` auf `0`, bleibt der Synonymkatalog deaktiviert und es werden
lediglich die ursprünglichen Schlüsselwörter der Eingabe verwendet.

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
    "lkns": ["AA.00.0010", "AA.00.0011"],
    "lkn": "AA.00.0010",
      "de": ["bar"],
      "fr": ["baz"]
    }
  }
}
```

Dieses Format wird vom GUI-Werkzeug erzeugt und von `synonyms.storage` eingelesen. Vorherige Dateien ohne `lkn`- oder `lkns`-Feld oder ohne Sprachaufteilung werden weiterhin unterstützt.


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

Die Python-Tests liegen im Verzeichnis `tests/`. Empfohlene Ausführung:

- Windows (PowerShell)
  - `py -3 -m venv venv`
  - `.\venv\Scripts\Activate.ps1`
  - `python -m pip install -r requirements.txt`
  - `python -m pytest -q`

- macOS/Linux
  - `python3 -m venv venv`
  - `source venv/bin/activate`
  - `python -m pip install -r requirements.txt`
  - `python -m pytest -q`

Beispiele
- Einzelne Datei: `python -m pytest tests/test_server.py -q`
- Einzelner Test: `python -m pytest tests/test_server.py::test_version_endpoint -q`
- Filter: `python -m pytest -k "synonyms and not connectivity" -q`

Hinweis: Einige Konnektivitätstests erfordern API‑Keys (z. B. `GEMINI_API_KEY`, `OPENAI_API_KEY`, `APERTUS_API_KEY`). Ohne Keys können diese mit `-k "not llm_connectivity"` übersprungen werden.

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


