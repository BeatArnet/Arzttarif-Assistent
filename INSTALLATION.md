# Installations- und Betriebsdokumentation: Arzttarif-Assistent

Dieses Dokument beschreibt die Einrichtung, das Deployment und den Betrieb des "Arzttarif-Assistenten", sowohl für die lokale Entwicklung als auch für den produktiven Einsatz auf einer Plattform wie Render.com.

**Inhaltsverzeichnis:**

1.  Projektübersicht & Wichtige Hinweise
2.  Voraussetzungen
3.  Lokale Einrichtung und Ausführung
4.  Deployment auf Render.com
5.  Betrieb und Wartung
6.  Urheber und Kontakt

---

## 1. Projektübersicht & Wichtige Hinweise

Der "Arzttarif-Assistent" ist eine Webanwendung, die medizinische Leistungstexte analysiert und basierend auf dem Schweizer Arzttarif (TARDOC und Pauschalen) Vorschläge zur Abrechnung generiert.

*   **Ohne Gewähr:** Dies ist eine Open-Source-Anwendung und ein Prototyp. Die Ergebnisse sind nicht verbindlich und können Fehler enthalten.
*   **Offizielle Quellen:**
    *   **OAAT Tarifbrowser:** Für verbindliche Tarifinformationen ist der offizielle Tarifbrowser zu konsultieren: [https://tarifbrowser.oaat-otma.ch/startPortal](https://tarifbrowser.oaat-otma.ch/startPortal)
    *   **FMH Tarifplattform:** Die Ärzteschaft kann sich hier orientieren: [https://www.tarifeambulant.fmh.ch/](https://www.tarifeambulant.fmh.ch/)
*   **Open Source:** Das Projekt ist auf GitHub verfügbar: [https://github.com/BeatArnet/Arzttarif-Assistent](https://github.com/BeatArnet/Arzttarif-Assistent)

**Architektur:**

*   **Backend:** Flask (Python) Anwendung (`server.py`).
*   **Frontend:** HTML, CSS und Vanilla JavaScript (`index.html`, `calculator.js`).
*   **Daten:** JSON-Dateien im `./data`-Verzeichnis, die direkt im Git-Repository gespeichert werden.
*   **KI-Service:** Google Gemini API.

## 2. Voraussetzungen

*   **Lokal:**
    *   Python (Version 3.9 oder höher)
    *   `pip` (Python Package Installer)
    *   Git
    *   Ein Google Gemini API Key
*   **Für Deployment:**
    *   Ein Git-Hosting-Konto (z.B. GitHub).
    *   Ein Hosting-Anbieter-Konto (z.B. Render.com).

## 3. Lokale Einrichtung und Ausführung

**3.1. Repository klonen**
```bash
git clone https://github.com/BeatArnet/Arzttarif-Assistent.git
cd Arzttarif-Assistent
```

**3.2. Python-Umgebung einrichten (Empfohlen)**
```bash
python -m venv venv
# Windows:
venv\Scripts\activate
# macOS/Linux:
source venv/bin/activate
```

**3.4. Abhängigkeiten installieren**
```bash
pip install -r requirements.txt
```

**3.5. Umgebungsvariablen konfigurieren**
Erstelle eine Datei namens `.env` im Projektstammverzeichnis (diese Datei wird durch `.gitignore` ignoriert).
Inhalt der `.env`-Datei:
```env
GEMINI_API_KEY="DEIN_GEMINI_API_KEY"
```
Ersetze `DEIN_GEMINI_API_KEY` durch deinen Schlüssel.

**3.6. Anwendung lokal starten**
```bash
python server.py
```
Der Server startet standardmässig auf `http://127.0.0.1:8000`.

## 4. Deployment auf Render.com

**4.1. Vorbereitung**
1.  **`.gitignore`:** Stelle sicher, dass `.env` und andere sensible Dateien ignoriert werden.
2.  **`requirements.txt`:** Muss alle Abhängigkeiten enthalten (`Flask`, `requests`, `python-dotenv`, `gunicorn`).
3.  **`Procfile`:** Eine Datei namens `Procfile` im Stammverzeichnis mit dem Inhalt:
    ```
    web: gunicorn server:app --timeout 120
    ```
4.  **Git-Repository:** Stelle sicher, dass alle Änderungen committet und gepusht wurden.

**4.2. Konfiguration auf Render.com**
1.  Erstelle einen neuen "Web Service" und verbinde dein Git-Repository.
2.  **Build Command:** `pip install -r requirements.txt`
3.  **Start Command:** `gunicorn server:app --timeout 120`
4.  **Instance Type:** Wähle einen passenden Plan. **Wichtig:** Aufgrund des RAM-Bedarfs der Daten (>512 MB) ist mindestens der **"Standard"**-Plan erforderlich.
5.  **Environment Variables:** Füge eine Umgebungsvariable `GEMINI_API_KEY` mit deinem API-Schlüssel hinzu.

**4.3. Deployment**
Nach dem Erstellen des Services deployt Render automatisch. Die öffentliche URL wird im Dashboard angezeigt.

## 5. Betrieb und Wartung

*   **Datenaktualisierung:**
    *   Die JSON-Dateien im `./data`-Verzeichnis werden direkt in Git verwaltet.
    *   Um die Daten zu aktualisieren, committe und pushe einfach die geänderten JSON-Dateien. Render.com wird automatisch ein neues Deployment mit den neuen Daten starten.
*   **Log-Überwachung:** Überprüfe die Logs auf der Render.com-Plattform, um Fehler zu diagnostizieren.
*   **Abhängigkeiten:** Halte `requirements.txt` aktuell.

## 6. Urheber und Kontakt

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