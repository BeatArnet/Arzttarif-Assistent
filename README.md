# TARDOC und Pauschalen Assistent

Dies ist ein Prototyp einer Webanwendung zur Unterstützung bei der Abrechnung medizinischer Leistungen nach dem neuen Schweizer Arzttarif (TARDOC und Pauschalen). Die Anwendung nimmt eine Freitextbeschreibung einer medizinischen Leistung entgegen und schlägt die optimale Abrechnungsart (Pauschale oder TARDOC-Einzelleistung) vor. Sie kombiniert eine KI-basierte Leistungsidentifikation mit detaillierter lokaler Regel- und Bedingungsprüfung.

## Versionsübersicht

### V1.1
- JSON-Datendateien wurden umbenannt und der ehemals kombinierte TARDOC-Datensatz in **TARDOC_Tarifpositionen.json** und **TARDOC_Interpretationen.json** aufgeteilt.
- `server.py` sowie das README verwenden diese neuen Namen; `index.html` weist nun die Version "V1.1" aus.
- `utils.py` bietet ein Übersetzungssystem für Regelmeldungen und Condition-Typen in Deutsch, Französisch und Italienisch.
- In `regelpruefer_pauschale.py` sorgt eine Operator-Präzedenzlogik für korrektes "UND vor ODER" bei strukturierten Bedingungen.
- `evaluate_structured_conditions` unterstützt einen konfigurierbaren
  `GruppenOperator` (Standard `UND`, einstellbar über
  `DEFAULT_GROUP_OPERATOR` in `regelpruefer_pauschale.py`) für die Verknüpfung
  der Bedingungsgruppen. Fehlt diese Spalte, wird der Operator heuristisch
  bestimmt: Wenn mehrere Gruppen vorhanden sind und in der ersten Gruppe
  mindestens eine Zeile den Operator `ODER` nutzt, gilt `ODER` global.
- Optional kann ein `debug`-Flag genutzt werden, um die pro Gruppe erzeugten
  Booleschen Ausdrücke samt Ergebnis auszugeben.
- Die mehrsprachigen Prompts für LLM Stufe 1 und Stufe wurden in  `prompts.py` ausgelagert
- Funktionale Erweiterung umfassen:
    - interaktive Info-Pop-ups, 
    - mehrsprachige Oberfläche, 
    - erweiterte Suchhilfen, 
    - Fallback-Logik für Pauschalen, 
    - mobile Ansicht, 
    - zusätzliche Beispieldaten 
    - sowie Korrekturen bei Mengenbegrenzungen und ICD-Verarbeitung.

### V1.0
- Erste lauffähige Version des Prototyps.

## Beschreibung

Der Assistent analysiert die eingegebene Leistungsbeschreibung mithilfe eines Large Language Models (Google Gemini), um relevante Leistungspositionen (LKNs) zu identifizieren. Ein Backend-Regelwerk prüft die Konformität dieser LKNs (Mengen, Kumulationen etc.). Die Kernlogik entscheidet dann, ob eine Pauschale für die (regelkonformen) Leistungen anwendbar ist. Falls ja, wird die passendste Pauschale ausgewählt und deren Bedingungen detailliert geprüft. Falls keine Pauschale greift, wird eine Abrechnung nach TARDOC-Einzelleistungen vorbereitet.

Das Frontend zeigt das Ergebnis übersichtlich an, mit Details zur initialen KI-Analyse, der Regelprüfung und zur finalen Abrechnungsempfehlung (inklusive Pauschalenbegründung und detaillierter Bedingungsprüfung).

## Mehrsprachigkeit

Der Assistent ist in den drei Landessprachen DE, FR und IT verfügbar. Die Sprache richtet sich nach der Browsereinstellung, sie kann aber auch manuell geändert werden. Allerdings sollte man die Seite dann neu aufrufen, damit alles neu initialisiert wird. Es zeigt sich, dass die Antworten der KI nicht in allen drei Sprachen gleich (gut) funktioniert. An der Kosnistenz der Antworten muss noch gearbeitet werden.

## Kernlogik / Architektur

1.  **Frontend (`index.html`, `calculator.js`):**
    *   Nimmt Benutzereingaben (Text, optionale ICDs, GTINs, Kontext wie Alter/Geschlecht) entgegen.
    *   Sendet die Anfrage an das Backend.
    *   Empfängt das strukturierte Ergebnis vom Backend.
    *   Stellt die Ergebnisse benutzerfreundlich dar:
        *   Prominentes Hauptergebnis (Pauschale oder TARDOC).
        *   Aufklappbare Details für:
            *   KI-Analyse (Stufe 1: LKN-Identifikation).
            *   KI-Analyse (Stufe 2: Mapping von TARDOC E/EZ-LKNs auf Pauschalen-Bedingungs-LKNs, falls relevant).
            *   Regelprüfung der Einzelleistungen.
            *   Details zur ausgewählten Pauschale (inkl. Begründung der Auswahl und detaillierter, gruppierter Bedingungsprüfung mit visuellen Statusindikatoren).
            *   Details zur TARDOC-Abrechnung (falls zutreffend).
    *   Zeigt Ladeindikatoren (Text und Maus-Spinner).

2.  **Backend (Python/Flask - `server.py`):**
    *   Empfängt Anfragen vom Frontend.
    *   **LLM Stufe 1 (`call_gemini_stage1`):** Identifiziert LKNs und extrahiert Kontext aus dem Benutzertest mithilfe von Google Gemini. Der übergebene Ausschnitt aus `LKAAT_Leistungskatalog.json` wird nun anhand der Benutzereingabe gefiltert (max. 200 Treffer). Sehr häufige Wörter werden dabei ignoriert.
    *   **Regelprüfung LKN (`regelpruefer.py`):** Prüft die identifizierten LKNs auf Konformität mit TARDOC-Regeln (Menge, Kumulation etc.) basierend auf den im TARDOC-Datensatz eingebetteten Regeldefinitionen.
    *   **Pauschalenpotenzial-Prüfung:** Stellt frühzeitig fest, ob aufgrund der von LLM Stufe 1 gefundenen LKN-Typen überhaupt eine Pauschale in Frage kommt.
    *   **Kontextanreicherung (LKN-Mapping - `call_gemini_stage2_mapping`):**
        *   Wird nur ausgeführt, wenn Pauschalenpotenzial besteht und TARDOC E/EZ-LKNs vorhanden sind, die potenziell durch Pauschalen-Komponenten abgedeckt sein könnten.
        *   Versucht, TARDOC E/EZ-LKNs auf funktional äquivalente LKNs (oft Typ P/PZ) zu mappen, die als Bedingungen in den potenziellen Pauschalen vorkommen. Die Kandidatenliste für das Mapping wird dynamisch aus den Bedingungen der potenziell relevanten Pauschalen generiert.
    *   **Pauschalen-Anwendbarkeitsprüfung (`regelpruefer_pauschale.py`):**
        *   **Potenzielle Pauschalen finden:** Identifiziert mögliche Pauschalen basierend auf den regelkonformen LKNs (aus `rule_checked_leistungen`) unter Verwendung von `PAUSCHALEN_Leistungspositionen.json` und den LKN-Bedingungen in `PAUSCHALEN_Bedingungen.json`.
        *   **Strukturierte Bedingungsprüfung (`evaluate_structured_conditions`):** Prüft für jede potenzielle Pauschale, ob ihre Bedingungsgruppen erfüllt sind. Zwischen den Gruppen gilt ein konfigurierbarer `GruppenOperator` (Standard `UND`, siehe `DEFAULT_GROUP_OPERATOR`). Innerhalb einer Gruppe wird die Spalte `Operator` (`UND`/`ODER`) jeder Zeile beachtet und mit "UND vor ODER" ausgewertet. So lässt sich aus einer Zeilenfolge wie
          1. `SEITIGKEIT = B` (Operator `ODER`)
          2. `ANZAHL >= 2`  (Operator `UND`)
          3. `LKN IN LISTE OP`
          der Ausdruck `(SEITIGKEIT = B ODER ANZAHL >= 2) UND LKN IN LISTE OP` ableiten. Berücksichtigt wird zudem das `useIcd`-Flag.
        *   Bei gesetztem `debug=True` gibt die Funktion die pro Gruppe generierten Booleschen Ausdrücke samt Ergebnis aus.
        *   **Auswahl der besten Pauschale (`determine_applicable_pauschale`):** Wählt aus den struktur-gültigen Pauschalen die "komplexeste passende" (niedrigster Suffix-Buchstabe, z.B. A vor B vor E) aus der bevorzugten Kategorie (spezifisch vor Fallback).
        *   Generiert detailliertes HTML für die Bedingungsprüfung und eine Begründung der Auswahl.
    *   **Entscheidung & TARDOC-Vorbereitung:** Entscheidet "Pauschale vor TARDOC". Wenn keine Pauschale anwendbar ist, bereitet es die TARDOC-Liste (`regelpruefer.prepare_tardoc_abrechnung`) vor.
    *   Sendet das Gesamtergebnis (inkl. aller Detailstufen) zurück an das Frontend.

3.  **Daten (`./data` Verzeichnis):** Lokale JSON-Dateien als Wissensbasis.
    *   `LKAAT_Leistungskatalog.json`: LKNs, Typen, Beschreibungen.
    *   `PAUSCHALEN_Leistungspositionen.json`: Direkte LKN-zu-Pauschale-Links.
    *   `PAUSCHALEN_Pauschalen.json`: Pauschalendefinitionen.
    *   `PAUSCHALEN_Bedingungen.json`: Strukturierte Bedingungen für Pauschalen.
        Das Feld `BedingungsID` ist **nicht eindeutig**. Es dient lediglich als
        Kennzeichen einer gemeinsamen Bedingungsvorlage, die in mehreren
        Pauschalen verwendet wird.
    *   `PAUSCHALEN_Tabellen.json`: Nachschlagetabellen für Codes in Bedingungen.
    *   `TARDOC_Tarifpositionen.json`: Details und Regeldefinitionen für TARDOC-Einzelleistungen.
    *   `TARDOC_Interpretationen.json`: Erläuterungen und Kapiteltexte zu TARDOC-Positionen.

## Technologie-Stack

*   **Backend:** Python 3, Flask, Gunicorn (für Produktion)
*   **Frontend:** HTML5, CSS3, Vanilla JavaScript
*   **KI-Service:** Google Gemini API (via REST)
*   **Daten:** JSON
*   **Versionierung großer Dateien:** Git LFS

## Setup und Installation (Lokal)

1.  **Voraussetzungen:**
    *   Python (z.B. 3.11.x)
    *   `pip` (Python Package Installer)
    *   Git
    *   Git LFS ([https://git-lfs.com](https://git-lfs.com))
2.  **Repository klonen:**
    ```bash
    git clone <repository_url>
    cd <repository_directory>
    ```
3.  **Git LFS Dateien holen (falls noch nicht geschehen):**
    ```bash
    git lfs pull
    ```
4.  **Virtuelle Umgebung (Empfohlen):**
    ```bash
    python -m venv venv
    # Windows:
    venv\Scripts\activate
    # macOS/Linux:
    source venv/bin/activate
    ```
5.  **Abhängigkeiten installieren:**
    ```bash
    pip install -r requirements.txt
    ```
6.  **(Optional) JSON-Daten bereinigen:**
    Einige Datendateien enthalten Steuerzeichen, die beim Parsen Fehler
    verursachen können. Bereinige eine Datei mit:
    ```bash
    python clean_json.py data/TARDOC_Interpretationen.json
    ```
    Es entsteht eine `*.clean.json`-Datei, die zum Testen verwendet werden kann.

7.  **(Optional) Pauschalen-Tabellen exportieren:**
    Nutze `export_pauschalen_table.py`, um binäre Werte in den Feldern
    `Ebene` und `Gruppe` zu bereinigen.
    ```bash
    python export_pauschalen_table.py data/PAUSCHALEN_Bedingungen.json \
        data/PAUSCHALEN_Bedingungen.clean.json
    ```
8.  **API-Schlüssel konfigurieren:**
    *   Erstelle eine Datei namens `.env` im Hauptverzeichnis.
    *   Füge deinen Google Gemini API-Schlüssel hinzu:
        ```env
        GEMINI_API_KEY="DEIN_API_SCHLUESSEL_HIER"
        # Optional: GEMINI_MODEL="gemini-1.5-pro-latest"
        ```
9.  **Anwendung starten:**
    ```bash
    python server.py
    ```
    Öffne `http://127.0.0.1:8000` im Browser.

## Deployment auf Render.com

1.  **Vorbereitung:**
    *   Stelle sicher, dass `requirements.txt` existiert und `Flask`, `requests`, `python-dotenv`, `gunicorn` enthält.
    *   Erstelle eine `Procfile`-Datei im Stammverzeichnis:
        ```
        web: gunicorn server:app --timeout 120 --workers 1
        ```
    *   Initialisiere Git LFS im Repository, falls noch nicht geschehen (`git lfs install`), und verfolge die JSON-Dateien im `data`-Ordner (`git lfs track "data/*.json"`). Committe `.gitattributes` und die Pointer-Dateien.
    *   Stelle sicher, dass `.env` in `.gitignore` ist.
2.  **Render.com Setup:**
    *   Erstelle einen neuen "Web Service" auf Render.com und verbinde dein Git-Repository.
    *   **Build Command:** `pip install -r requirements.txt`
    *   **Start Command:** `gunicorn server:app --timeout 120 --workers 1` 
    *   **Environment Variables:** Setze `GEMINI_API_KEY` (und optional `PYTHON_VERSION`, `GEMINI_MODEL`) im Render.com Dashboard.
3.  **Deployment:** Pushe deine Änderungen. Render.com sollte automatisch deployen und Git LFS-Dateien korrekt behandeln.

## Benötigte Dateien (Struktur)

```
.
├── .env                   # API Schlüssel (lokal, nicht versionieren!)
├── .gitattributes         # Konfiguration für Git LFS
├── .gitignore             # Ignoriert .env, __pycache__ etc.
├── data/                  # Verzeichnis für alle JSON Daten
│   ├── LKAAT_Leistungskatalog.json
│   ├── PAUSCHALEN_Leistungspositionen.json
│   ├── PAUSCHALEN_Pauschalen.json
│   ├── PAUSCHALEN_Bedingungen.json
│   ├── TARDOC_Tarifpositionen.json
│   ├── TARDOC_Interpretationen.json
│   ├── PAUSCHALEN_Tabellen.json
├── server.py              # Flask Backend Logik
├── calculator.js          # Frontend JavaScript Logik
├── index.html             # Haupt-HTML-Datei
├── regelpruefer.py        # Backend Modul für TARDOC LKN Regelprüfung
├── regelpruefer_pauschale.py # Backend Modul für Pauschalen Bedingungsprüfung
├── utils.py               # Hilfsfunktionen (z.B. escape)
├── PRD.txt                # Product Requirements Document
├── README.md              # Dieses README
├── requirements.txt       # Python Abhängigkeiten
├── Procfile               # Für Render.com
└── favicon.ico / .svg     # Favicons
```

## Qualitätstests

Die Datei `data/beispiele.json` enthält fünfzehn Beispielabfragen in Deutsch,
Französisch und Italienisch. Für jede Abfrage sind im
`data/baseline_results.json` die erwarteten Tarife hinterlegt. Dort ist nun auch
der Klartext der jeweiligen Frage gespeichert, sodass die passenden Baselines
einfach gefunden werden können. Über `quality.html` lassen sich diese Beispiele
gegen die Baselines testen. Die gleichen Tests können alternativ auf der
Kommandozeile gestartet werden:

```bash
python run_quality_tests.py
```
Das Skript ruft für jedes Beispiel das Backend-Endpunkt `/api/test-example` auf
und zeigt an, ob das Ergebnis mit dem Baseline-Wert übereinstimmt.

## Unittests mit `pytest`

Die Python-Tests liegen im Verzeichnis `tests/` und werden mit `pytest`
ausgeführt. Vor dem Start der Tests müssen sämtliche Abhängigkeiten installiert
sein:

```bash
pip install -r requirements.txt
pytest
```

Die Tests setzen unter anderem Flask und weitere Pakete aus der
`requirements.txt` voraus.

## Disclaimer

Alle Auskünfte erfolgen ohne Gewähr. Diese Anwendung ist ein Prototyp und dient nur zu Demonstrations- und Testzwecken. Für offizielle und verbindliche Informationen konsultieren Sie bitte das Portal  OAAT-OTMA AG: [https://tarifbrowser.oaat-otma.ch/startPortal](https://tarifbrowser.oaat-otma.ch/startPortal).
