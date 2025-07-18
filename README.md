# Arzttarif-Assistent

Dies ist ein Prototyp einer Webanwendung zur Unterstützung bei der Abrechnung medizinischer Leistungen nach dem neuen Schweizer Arzttarif (TARDOC und Pauschalen). Die Anwendung nimmt eine Freitextbeschreibung einer medizinischen Leistung entgegen und schlägt die optimale Abrechnungsart (Pauschale oder TARDOC-Einzelleistung) vor. Sie kombiniert eine KI-basierte Leistungsidentifikation mit detaillierter lokaler Regel- und Bedingungsprüfung.

## Wichtige Hinweise

*   **Ohne Gewähr:** Der Arzttarif-Assistent ist eine Open-Source-Anwendung und ein Prototyp. Die Ergebnisse können Fehler enthalten und sind nicht verbindlich.
*   **Offizielle Quellen:**
    *   Für verbindliche Tarifinformationen und zur Überprüfung der Resultate konsultieren Sie bitte den offiziellen **OAAT Tarifbrowser**: [https://tarifbrowser.oaat-otma.ch/startPortal](https://tarifbrowser.oaat-otma.ch/startPortal)
    *   Die Ärzteschaft kann sich zudem auf der **Tarifplattform der FMH** orientieren: [https://www.tarifeambulant.fmh.ch/](https://www.tarifeambulant.fmh.ch/)
*   **Open Source:** Das Projekt ist öffentlich auf GitHub verfügbar: [https://github.com/BeatArnet/Arzttarif-Assistent](https://github.com/BeatArnet/Arzttarif-Assistent)

## Versionsübersicht

### V2.2 (Aktuell)
- Dokumentation (README.md, INSTALLATION.md) aktualisiert mit den neuesten Hinweisen und Versionsdetails.

### V2.0
- **Qualitätstests und Baseline-Vergleiche:** Einführung einer neuen Testseite (`quality.html`, `quality.js`) und eines Skripts (`run_quality_tests.py`) zum automatisierten Vergleich von Beispielen mit Referenzwerten (`baseline_results.json`). Ein neuer Backend-Endpunkt `/api/quality` wurde dafür in `server.py` hinzugefügt.
- **Erweiterte Pop-up-Funktionen:** Pop-up-Fenster im Frontend sind nun verschiebbar und in der Größe anpassbar (`calculator.js`).
- **Verbesserte Pauschalenlogik:** Die Auswertung strukturierter Pauschalenbedingungen erfolgt nun über den Orchestrator `evaluate_pauschale_logic_orchestrator` in `regelpruefer_pauschale.py`, begleitet von neuen Unittests.
- **Daten- und Funktionsumfang:** Zusätzliche Datendateien wie `DIGNITAETEN.json` wurden integriert. Die TARDOC-Daten wurden in `TARDOC_Tarifpositionen.json` und `TARDOC_Interpretationen.json` aufgeteilt.
- **Verbesserte Textaufbereitung:** Neue Hilfsfunktionen in `utils.py` zur Erweiterung von Komposita (`expand_compound_words`) und zur Synonym-Erkennung (`SYNONYM_MAP`).
- **Ausgelagerte Prompts:** Die Prompt-Definitionen für die KI wurden in die separate Datei `prompts.py` ausgelagert und unterstützen Mehrsprachigkeit.

### V1.1
- JSON-Datendateien wurden umbenannt und der ehemals kombinierte TARDOC-Datensatz in **TARDOC_Tarifpositionen.json** und **TARDOC_Interpretationen.json** aufgeteilt.
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

## Kernlogik / Architektur

1.  **Frontend (`index.html`, `calculator.js`):**
    *   Nimmt Benutzereingaben (Text, optionale ICDs, GTINs, Kontext wie Alter/Geschlecht) entgegen.
    *   Sendet die Anfrage an das Backend.
    *   Empfängt das strukturierte Ergebnis vom Backend.
    *   Stellt die Ergebnisse benutzerfreundlich dar.

2.  **Backend (Python/Flask - `server.py`):**
    *   Empfängt Anfragen vom Frontend.
    *   **LLM Stufe 1 (`call_gemini_stage1`):** Identifiziert LKNs und extrahiert Kontext aus dem Benutzertest mithilfe von Google Gemini.
    *   **Regelprüfung LKN (`regelpruefer.py`):** Prüft die identifizierten LKNs auf Konformität mit TARDOC-Regeln.
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
    *   Füge deinen Google Gemini API-Schlüssel hinzu:
        ```env
        GEMINI_API_KEY="DEIN_API_SCHLUESSEL_HIER"
        ```
6.  **Anwendung starten:**
    ```bash
    python server.py
    ```
    Öffne `http://127.0.0.1:8000` im Browser.

## Deployment auf Render.com

Die Anwendung kann auf Plattformen wie Render.com deployed werden. Hierfür sind eine `Procfile` und die Konfiguration von Umgebungsvariablen für den API-Schlüssel notwendig. Der `Standard`-Plan (oder höher) wird aufgrund des RAM-Bedarfs (>512 MB) empfohlen.

## Qualitätstests

Die Datei `data/beispiele.json` enthält Testfälle. Mit `run_quality_tests.py` können diese gegen die erwarteten Ergebnisse in `data/baseline_results.json` geprüft werden:
```bash
python run_quality_tests.py
```

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
