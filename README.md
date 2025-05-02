# TARDOC und Pauschalen Assistent

Dies ist ein Prototyp einer Webanwendung zur Unterstützung bei der Abrechnung medizinischer Leistungen nach dem neuen Schweizer Arzttarif (TARDOC und Pauschalen). Die Anwendung nimmt eine Freitextbeschreibung einer medizinischen Leistung entgegen und schlägt die optimale Abrechnungsart (Pauschale oder TARDOC-Einzelleistung) vor, basierend auf einem zweistufigen LLM-Ansatz und lokaler Regelprüfung.

## Beschreibung

Der Assistent analysiert die eingegebene Leistungsbeschreibung mithilfe eines Large Language Models (Google Gemini), um relevante Leistungspositionen (LKNs) zu identifizieren. Anschliessend prüft ein Backend-Regelwerk die Konformität dieser LKNs (Mengen, Kumulationen etc.). Die Kernlogik entscheidet dann, ob eine Pauschale für die (regelkonformen) Leistungen anwendbar ist. Falls ja, wird die passendste Pauschale ausgewählt (ggf. mit LLM-Ranking) und deren Bedingungen geprüft. Falls keine Pauschale greift, wird eine Abrechnung nach TARDOC-Einzelleistungen vorbereitet.

Das Frontend zeigt das Ergebnis übersichtlich an, mit Details zur LLM-Analyse, Regelprüfung und zur finalen Abrechnungsempfehlung (inkl. Pauschalenbegründung und möglicher ICD-Codes).

## Kernlogik / Architektur

1.  **Frontend (HTML/CSS/JS - `index.html`, `calculator.js`):**
    *   Nimmt Benutzereingaben (Text, ICD, GTIN) entgegen.
    *   Sendet die Anfrage an das Backend.
    *   Empfängt das strukturierte Ergebnis vom Backend.
    *   Stellt die Ergebnisse benutzerfreundlich dar (prominentes Hauptergebnis, aufklappbare Details für LLM-Analyse, Regelprüfung, Pauschalenbegründung, ICDs etc.).
    *   Zeigt Ladeindikatoren (Text und Maus-Spinner).
2.  **Backend (Python/Flask - `server.py`):**
    *   Empfängt Anfragen vom Frontend.
    *   **LLM Stufe 1 (`call_gemini_stage1`):** Identifiziert LKNs und extrahiert Kontext aus dem Benutzertest mithilfe von Google Gemini und dem lokalen Leistungskatalog. Validiert LKNs.
    *   **Regelprüfung LKN (`regelpruefer.py`):** Prüft die identifizierten LKNs auf Konformität mit TARDOC-Regeln (Menge, Kumulation etc.) basierend auf einem lokalen Regelwerk (`strukturierte_regeln_komplett.json`).
    *   **Pauschalen-Prüfung (`determine_applicable_pauschale`):**
        *   Sucht nach potenziellen Pauschalen basierend auf den *regelkonformen* LKNs unter Verwendung von `tblPauschaleLeistungsposition.json`, `tblPauschaleBedingungen.json` und `tblTabellen.json`.
        *   **LLM Stufe 2 (`call_gemini_stage2_ranking`):** Optionales Ranking bei mehreren potenziellen Pauschalen.
        *   Wählt die beste Pauschale aus.
        *   Prüft die Bedingungen der ausgewählten Pauschale (`regelpruefer_pauschale.py`, `tblPauschaleBedingungen.json`).
        *   Sammelt Zusatzinfos (Erklärung, ICDs).
    *   **Entscheidung & TARDOC-Vorbereitung:** Entscheidet "Pauschale vor TARDOC". Wenn keine Pauschale anwendbar ist, bereitet es die TARDOC-Liste (`prepare_tardoc_abrechnung`) vor.
    *   Sendet das Gesamtergebnis zurück an das Frontend.
3.  **Daten (`./data` Verzeichnis):** Lokale JSON-Dateien als Wissensbasis für Katalog, Pauschalen, Bedingungen, TARDOC-Details und Regeln.

## Technologie-Stack

*   **Backend:** Python 3, Flask
*   **Frontend:** HTML5, CSS3, Vanilla JavaScript
*   **LLM:** Google Gemini API (via REST)
*   **Daten:** JSON

## Setup / Installation

1.  **Voraussetzungen:**
    *   Python 3.x installiert.
    *   `pip` (Python package installer).
2.  **Repository klonen:**
    ```bash
    git clone <repository_url>
    cd <repository_directory>
    ```
3.  **Virtuelle Umgebung (Empfohlen):**
    ```bash
    python -m venv venv
    # Windows
    .\venv\Scripts\activate
    # macOS/Linux
    source venv/bin/activate
    ```
4.  **Abhängigkeiten installieren:**
    *   Erstelle eine Datei `requirements.txt` mit folgendem Inhalt:
        ```txt
        Flask
        requests
        python-dotenv
        ```
    *   Installiere die Pakete:
        ```bash
        pip install -r requirements.txt
        ```
5.  **API-Schlüssel konfigurieren:**
    *   Erstelle eine Datei namens `.env` im Hauptverzeichnis des Projekts.
    *   Füge deinen Google Gemini API-Schlüssel hinzu:
        ```env
        GEMINI_API_KEY=DEIN_API_SCHLUESSEL_HIER
        # Optional: Spezifisches Modell auswählen (Standard ist gemini-1.5-flash-latest)
        # GEMINI_MODEL=gemini-1.5-pro-latest
        ```
    *   Ersetze `DEIN_API_SCHLUESSEL_HIER` mit deinem tatsächlichen Schlüssel.
6.  **Daten bereitstellen:**
    *   Stelle sicher, dass das Verzeichnis `data` im Hauptverzeichnis existiert.
    *   Platziere alle benötigten JSON-Datendateien (siehe unten) in diesem Verzeichnis.
    *   Stelle sicher, dass die LKN-Regelwerkdatei (z.B. `strukturierte_regeln_komplett.json`) im `data`-Verzeichnis liegt und der Pfad in `server.py` korrekt ist (`REGELWERK_PATH`).

## Benötigte Dateien
.
├── .env                   # API Schlüssel und Konfiguration (NICHT versionieren!)
├── data/                  # Verzeichnis für alle JSON Daten
│   ├── tblLeistungskatalog.json
│   ├── tblPauschaleLeistungsposition.json
│   ├── tblPauschalen.json
│   ├── tblPauschaleBedingungen.json
│   ├── TARDOCGesamt_optimiert_Tarifpositionen.json
│   ├── tblTabellen.json
│   └── strukturierte_regeln_komplett.json # (Beispielname für LKN-Regeln)
├── server.py              # Flask Backend Logik
├── calculator.js          # Frontend JavaScript Logik
├── index.html             # Haupt-HTML-Datei
├── regelpruefer.py        # Backend Modul für TARDOC LKN Regelprüfung
├── regelpruefer_pauschale.py # Backend Modul für Pauschalen Bedingungsprüfung
├── PRD.txt                # Product Requirements Document (dieses Dokument)
├── README.md              # Dieses README
└── requirements.txt       # Python Abhängigkeiten
└── favicon.ico / .svg     # Favicons

## Disclaimer

Alle Auskünfte erfolgen ohne Gewähr. Diese Anwendung ist ein Prototyp und dient nur zu Demonstrations- und Testzwecken. Für offizielle und verbindliche Informationen konsultieren Sie bitte das TARDOC Online-Portal der Oaat AG / Otma SA: https://tarifbrowser.oaat-otma.ch/startPortal.

## Anwendung starten

Führe den Flask-Server aus dem Hauptverzeichnis des Projekts aus:

```bash
python server.py