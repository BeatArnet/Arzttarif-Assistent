# TARDOC und Pauschalen Assistent

Dies ist ein Prototyp einer Webanwendung zur Unterstützung bei der Abrechnung medizinischer Leistungen nach dem neuen Schweizer Arzttarif (TARDOC und Pauschalen). Die Anwendung nimmt eine Freitextbeschreibung einer medizinischen Leistung entgegen, analysiert diese mithilfe von KI und lokalen Regelwerken und schlägt die optimale Abrechnungsart (Pauschale oder TARDOC-Einzelleistung) vor.

## Projektziel und Funktionalität

Der "TARDOC und Pauschalen Assistent" zielt darauf ab, medizinischem Fachpersonal eine intuitive Hilfestellung bei der komplexen Aufgabe der korrekten Tarifanwendung im neuen Schweizer System zu bieten.

**Kernfunktionen:**

1.  **Leistungsidentifikation:**
    *   Eine Freitexteingabe der erbrachten medizinischen Leistung wird von einem Large Language Model (Google Gemini) analysiert.
    *   Das LLM identifiziert potenziell relevante Leistungskatalog-Nummern (LKNs) und extrahiert wichtige Kontextinformationen (z.B. Dauer, Menge).
    *   Die vom LLM vorgeschlagenen LKNs werden gegen einen lokalen Leistungskatalog validiert.

2.  **Regelbasierte Prüfung:**
    *   Die validierten LKNs durchlaufen eine detaillierte lokale Regelprüfung (basierend auf `strukturierte_regeln_komplett.json`).
    *   Diese Prüfung berücksichtigt TARDOC-spezifische Regeln wie Mengenbeschränkungen, Kumulationsverbote, Alters- und Geschlechtsrestriktionen etc.
    *   Das Ergebnis ist eine Liste regelkonformer Leistungen mit potenziell angepassten Mengen.

3.  **Pauschalen-Analyse und -Auswahl:**
    *   **Potenzialprüfung:** Es wird frühzeitig geprüft, ob die identifizierten LKNs überhaupt eine Pauschalenabrechnung nahelegen.
    *   **Kontextanreicherung (Mapping):** Falls TARDOC-Einzelleistungen (Typ E/EZ) vorliegen, die potenziell durch Pauschalenkomponenten abgedeckt sein könnten, versucht ein zweiter LLM-Schritt, diese auf funktional äquivalente LKNs zu mappen, die typischerweise in Pauschalenbedingungen vorkommen (z.B. Anästhesie-LKNs).
    *   **Strukturierte Bedingungsprüfung:** Für alle potenziellen Pauschalen (identifiziert über direkte LKN-Verknüpfungen oder LKNs in Bedingungslisten/-tabellen) werden die detaillierten, strukturierten Bedingungen (`tblPauschaleBedingungen.json`) ausgewertet. Dies beinhaltet UND/ODER-Logiken zwischen Bedingungsgruppen und die Prüfung einzelner Kriterien (ICD, GTIN, LKN, Alter, Geschlecht etc.). Das `useIcd`-Flag aus dem Frontend beeinflusst die ICD-Prüfung.
    *   **Auswahl der besten Pauschale:** Aus allen Pauschalen, die ihre strukturierten Bedingungen erfüllen, wird die "komplexeste passende" ausgewählt (Priorisierung spezifischer Pauschalen, dann Sortierung nach Suffix).

4.  **Entscheidung und Ergebnisdarstellung:**
    *   Die Logik folgt dem Grundsatz "Pauschale vor TARDOC".
    *   Ist eine Pauschale anwendbar, wird diese als Ergebnis präsentiert.
    *   Andernfalls wird eine Abrechnung nach TARDOC-Einzelleistungen vorbereitet.
    *   Das Frontend (`index.html`, `calculator.js`) stellt das Ergebnis übersichtlich dar, inklusive:
        *   Hauptergebnis (Pauschale oder TARDOC).
        *   Aufklappbare Details zur LLM-Analyse (Stufe 1 und ggf. Stufe 2 Mapping).
        *   Details zur Regelprüfung jeder Einzelleistung.
        *   Bei Pauschalen: Begründung der Auswahl und eine detaillierte, gruppierte Ansicht der erfüllten/nicht erfüllten Bedingungen mit visuellen Indikatoren.
        *   Bei TARDOC: Eine Liste der abrechenbaren Positionen.

## Architekturübersicht

Die Anwendung ist als Client-Server-Architektur aufgebaut:

*   **Frontend (Client):**
    *   `index.html`: Struktur der Benutzeroberfläche.
    *   `calculator.js`: JavaScript-Logik für Benutzereingaben, API-Kommunikation mit dem Backend und dynamische Darstellung der Ergebnisse. Lädt lokale JSON-Daten für Frontend-spezifische Anzeigen (z.B. LKN-Beschreibungen).

*   **Backend (Server - Python/Flask mit Gunicorn):**
    *   `server.py`: Hauptanwendung, die API-Endpunkte bereitstellt, Anfragen verarbeitet und die Kernlogik orchestriert.
    *   `regelpruefer.py`: Modul für die Regelprüfung von TARDOC-Einzelleistungen.
    *   `regelpruefer_pauschale.py`: Modul für die komplexe Logik der Pauschalenfindung und -bedingungsprüfung.
    *   `utils.py`: Allgemeine Hilfsfunktionen.
    *   `gunicorn_config.py`: Stellt sicher, dass beim Start von Gunicorn-Workern (im Produktivbetrieb) die notwendigen Daten geladen werden.

*   **Datenbasis (`./data` Verzeichnis):**
    Eine Sammlung von JSON-Dateien dient als lokale Wissensbasis für Tarife, Regeln und Bedingungen:
    *   `tblLeistungskatalog.json`: Katalog aller LKNs mit Typen und Beschreibungen.
    *   `tblPauschaleLeistungsposition.json`: Direkte Zuordnungen von LKNs zu Pauschalen.
    *   `tblPauschalen.json`: Definitionen der Pauschalen (Code, Text, Taxpunkte).
    *   `tblPauschaleBedingungen.json`: Detaillierte, strukturierte Bedingungen für jede Pauschale (inkl. UND/ODER-Logik).
    *   `tblTabellen.json`: Nachschlagetabellen (z.B. für ICD-Codes, spezifische LKN-Listen), die in Pauschalenbedingungen referenziert werden.
    *   `TARDOCGesamt_optimiert_Tarifpositionen.json`: Details zu TARDOC-Einzelleistungen (AL, IPL, etc.).
    *   `strukturierte_regeln_komplett.json`: Das Regelwerk für die TARDOC-Einzelleistungsprüfung.

*   **Externe Services:**
    *   **Google Gemini API:** Wird für die KI-gestützte Analyse des Freitextes (Stufe 1) und das Mapping von TARDOC-LKNs auf Pauschalen-Bedingungs-LKNs (Stufe 2) verwendet.

## Technologie-Stack

*   **Backend:** Python 3, Flask, Gunicorn
*   **Frontend:** HTML5, CSS3, Vanilla JavaScript
*   **KI-Service:** Google Gemini API (via REST)
*   **Daten:** JSON
*   **Versionierung großer Dateien:** Git LFS

## Setup und Ausführung

Für detaillierte Anweisungen zur lokalen Einrichtung und zum Deployment auf Plattformen wie Render.com, siehe die Datei `INSTALLATION.md`.

## Verzeichnisstruktur (Wichtige Dateien)

```
.
├── data/                  # JSON-Datenbasis
├── server.py              # Flask Backend
├── calculator.js          # Frontend JavaScript
├── index.html             # Haupt-HTML
├── regelpruefer.py        # Modul Regelprüfung LKN
├── regelpruefer_pauschale.py # Modul Regelprüfung Pauschalen
├── utils.py               # Hilfsfunktionen
├── gunicorn_config.py     # Gunicorn Konfiguration
├── requirements.txt       # Python Abhängigkeiten
├── Procfile               # Für Render.com
├── INSTALLATION.md        # Technische Installationsanleitung
└── README.md              # Diese Datei
```

## Disclaimer

Alle Auskünfte erfolgen ohne Gewähr. Diese Anwendung ist ein Prototyp und dient nur zu Demonstrations- und Testzwecken. Für offizielle und verbindliche Informationen konsultieren Sie bitte das TARDOC Online-Portal der Oaat AG / Otma SA: [https://tarifbrowser.oaat-otma.ch/startPortal](https://tarifbrowser.oaat-otma.ch/startPortal).
