Dokumentation für die Einrichtung, das Deployment und den Betrieb deines "TARDOC und Pauschalen Assistenten", sowohl lokal als auch auf Render.com.

**Dokumentation: TARDOC und Pauschalen Assistent**

**Inhaltsverzeichnis:**

1.  Projektübersicht
2.  Voraussetzungen
3.  Lokale Einrichtung und Ausführung
    *   Repository klonen
    *   Python-Umgebung einrichten
    *   Abhängigkeiten installieren
    *   Git LFS einrichten (für Datendateien)
    *   Umgebungsvariablen konfigurieren (lokal)
    *   Daten laden (Initial)
    *   Anwendung lokal starten
4.  Deployment auf Render.com
    *   Vorbereitung des Git-Repositories
    *   Neuen Web Service auf Render.com erstellen
    *   Konfiguration auf Render.com
    *   Deployment und Überprüfung
5.  Betrieb und Wartung
    *   Datenaktualisierung
    *   Log-Überwachung
    *   Abhängigkeiten aktualisieren
6.  Integration in deine Webseite

---

**1. Projektübersicht**

Der "TARDOC und Pauschalen Assistent" ist eine Webanwendung, die medizinische Leistungstexte analysiert und basierend auf dem Schweizer Arzttarif (TARDOC und Pauschalen) Vorschläge zur Abrechnung generiert. Die Anwendung nutzt eine Kombination aus lokalen Daten und Regelwerken sowie einer externen KI-API (Google Gemini) für die Textanalyse.

**Architektur:**

*   **Backend:** Flask (Python) Anwendung (`server.py`), die die Hauptlogik, Datenverarbeitung und API-Aufrufe handhabt.
*   **Frontend:** HTML, CSS und JavaScript (`index.html`, `calculator.js`) für die Benutzeroberfläche.
*   **Daten:** Lokale JSON-Dateien im `./data`-Verzeichnis, verwaltet mit Git LFS.
*   **KI-Service:** Google Gemini API für die Verarbeitung von Freitext-Eingaben.

**2. Voraussetzungen**

*   **Lokal:**
    *   Python (Version 3.9 oder höher empfohlen, z.B. 3.11.x)
    *   `pip` (Python Package Installer)
    *   Git
    *   Git LFS ([https://git-lfs.github.com/](https://git-lfs.github.com/))
    *   Ein Google Gemini API Key
*   **Für Deployment:**
    *   Ein Git-Hosting-Konto (z.B. GitHub, GitLab), das Git LFS unterstützt.
    *   Ein Render.com-Konto.

**3. Lokale Einrichtung und Ausführung**

**3.1. Repository klonen**
Wenn das Projekt bereits in einem Git-Repository existiert:
```bash
git clone <URL_DEINES_REPOSITORIES>
cd <PROJEKTORDNER>
```

**3.2. Python-Umgebung einrichten (Empfohlen)**
Es wird dringend empfohlen, eine virtuelle Umgebung zu verwenden:
```bash
python -m venv venv
# Windows:
venv\Scripts\activate
# macOS/Linux:
source venv/bin/activate
```

**3.3. Abhängigkeiten installieren**
Erstelle eine Datei `requirements.txt` im Stammverzeichnis deines Projekts mit folgendem Inhalt:
```txt
Flask
requests
python-dotenv
gunicorn
```
Installiere dann die Abhängigkeiten:
```bash
pip install -r requirements.txt
```

**3.4. Git LFS einrichten (für Datendateien)**
Dies ist notwendig, um die JSON-Dateien im `./data`-Verzeichnis effizient zu verwalten.
*Falls du das Repository bereits mit LFS geklont hast und die Dateien korrekt heruntergeladen wurden, ist dieser Schritt für die *Einrichtung* eventuell schon erledigt. Für die *initiale Konfiguration* eines neuen Repositories oder wenn LFS noch nicht genutzt wird:*

1.  **Git LFS installieren:** Stelle sicher, dass Git LFS auf deinem System installiert ist.
2.  **LFS im Repository initialisieren (einmalig pro Repository):**
    ```bash
    git lfs install
    ```
3.  **Dateien für LFS markieren:**
    ```bash
    git lfs track "data/*.json"
    ```
    Dies erstellt oder aktualisiert die Datei `.gitattributes`.
4.  **Änderungen committen:**
    ```bash
    git add .gitattributes
    git add data/*.json  # Wichtig, um die Pointer-Dateien zu Git hinzuzufügen
    git commit -m "Configure Git LFS for data files"
    ```
5.  **Dateien zu LFS pushen (wenn du der erste bist, der LFS für diese Dateien nutzt):**
    ```bash
    git push
    ```
    Wenn du das Repository klonst und LFS bereits eingerichtet war, sollten die Dateien beim `git clone` oder spätestens bei einem `git lfs pull` korrekt heruntergeladen werden.

**3.5. Umgebungsvariablen konfigurieren (lokal)**
Erstelle eine Datei namens `.env` im Stammverzeichnis deines Projekts (diese Datei sollte in `.gitignore` stehen und nicht versioniert werden!).
Inhalt der `.env`-Datei:
```env
GEMINI_API_KEY="DEIN_TATSÄCHLICHER_GEMINI_API_KEY"
# Optional, wenn du vom Default in server.py abweichen willst:
# GEMINI_MODEL="gemini-1.5-pro-latest" 
```
Ersetze `DEIN_TATSÄCHLICHER_GEMINI_API_KEY` durch deinen Schlüssel.

**3.6. Daten laden (Initial)**
Der Python-Server (`server.py`) enthält eine `load_data()`-Funktion, die beim Start aufgerufen wird und die JSON-Dateien aus dem `./data`-Verzeichnis lädt. Stelle sicher, dass das `data`-Verzeichnis mit allen benötigten JSON-Dateien vorhanden ist.

**3.7. Anwendung lokal starten**
Führe das Backend aus:
```bash
python server.py
```
Der Server sollte starten (standardmäßig auf `http://127.0.0.1:8000`). Öffne diese Adresse in deinem Webbrowser, um die Anwendung zu sehen. Die Konsole zeigt Log-Ausgaben.

**4. Deployment auf Render.com**

**4.1. Vorbereitung des Git-Repositories**
1.  **`.gitignore`:** Stelle sicher, dass `.env`, `__pycache__/`, `*.pyc` und andere lokale/sensible Dateien in deiner `.gitignore`-Datei aufgeführt sind.
2.  **`requirements.txt`:** Muss wie oben beschrieben vorhanden sein.
3.  **`Procfile`:** Erstelle eine Datei namens `Procfile` (ohne Dateiendung) im Stammverzeichnis mit folgendem Inhalt:
    ```
    web: gunicorn server:app --timeout 120
    ```
    *   `server:app` geht davon aus, dass deine Flask-App-Instanz in `server.py` den Namen `app` hat (also `app = Flask(__name__)`).
    *   `--timeout 120` erhöht das Timeout für Worker auf 120 Sekunden, was bei längeren LLM-Aufrufen hilfreich sein kann. Passe dies bei Bedarf an.
4.  **Git LFS:** Stelle sicher, dass `.gitattributes` committet ist und du deine Änderungen (inklusive der LFS-Pointer) zu deinem Git-Provider (z.B. GitHub) gepusht hast.

**4.2. Neuen Web Service auf Render.com erstellen**
1.  Logge dich in dein Render.com Dashboard ein.
2.  Klicke auf "New +" und wähle "Web Service".
3.  Verbinde dein Git-Repository (z.B. GitHub). Wähle das korrekte Repository aus.

**4.3. Konfiguration auf Render.com**
Fülle die Felder wie folgt aus (siehe auch deinen Screenshot):

*   **Name:** Ein eindeutiger Name für deinen Service (z.B. `arzttarif-assistent`).
*   **Region:** Wähle eine passende Region (z.B. "Frankfurt (EU Central)").
*   **Branch:** Der Branch, der deployed werden soll (z.B. `master` oder `main`).
*   **Root Directory:** Leer lassen (wenn sich `requirements.txt`, `Procfile` etc. im Stammverzeichnis befinden).
*   **Runtime/Language:** Sollte automatisch als "Python" erkannt werden.
*   **Build Command:**
    ```
    pip install -r requirements.txt
    ```
*   **Start Command:**
    ```
    gunicorn server:app --timeout 120
    ```
    (Render.com sollte dies auch aus der `Procfile` übernehmen, aber es explizit zu setzen schadet nicht).
*   **Instance Type:** Wähle einen passenden Plan (z.B. "Free" zum Testen, später ggf. upgraden).
*   **Environment Variables:**
    *   Klicke auf "Add Environment Variable".
    *   **Key:** `GEMINI_API_KEY`, **Value:** `DEIN_TATSÄCHLICHER_GEMINI_API_KEY`
    *   (Optional) **Key:** `PYTHON_VERSION`, **Value:** `3.11.4` (oder deine spezifische Version)
    *   (Optional) **Key:** `GEMINI_MODEL`, **Value:** `gemini-1.5-flash-latest` (oder dein gewünschtes Modell)

**4.4. Deployment und Überprüfung**
1.  Klicke auf "Create Web Service".
2.  Render.com wird nun dein Repository klonen (inklusive Auflösung der Git LFS-Dateien), die Abhängigkeiten installieren und die Anwendung starten.
3.  Du kannst den Fortschritt im "Events"-Tab und die Logs im "Logs"-Tab verfolgen.
4.  Nach erfolgreichem Deployment stellt Render.com dir eine URL zur Verfügung (z.B. `https://dein-service-name.onrender.com`). Rufe diese URL im Browser auf, um deine Anwendung zu testen.

**5. Betrieb und Wartung**

*   **Datenaktualisierung:**
    *   Wenn du die JSON-Dateien im `./data`-Verzeichnis aktualisierst:
        1.  Füge die geänderten Dateien zu Git hinzu (`git add data/deine_datei.json`).
        2.  Committe die Änderungen (`git commit -m "Datenaktualisierung für XYZ"`).
        3.  Pushe die Änderungen zu deinem Git-Provider (`git push`).
        4.  Render.com sollte (je nach Einstellung) automatisch ein neues Deployment mit den aktualisierten Daten starten. Da die Daten via Git LFS verwaltet werden, werden die neuen Versionen heruntergeladen.
*   **Log-Überwachung:** Überprüfe regelmäßig die Logs deiner Anwendung auf Render.com ("Logs"-Tab), um Fehler oder unerwartetes Verhalten zu erkennen.
*   **Abhängigkeiten aktualisieren:** Halte deine `requirements.txt` aktuell und deploye neu, wenn du Bibliotheken aktualisierst.

**6. Integration in deine Webseite (arkons.ch)**

Sobald dein Assistent auf Render.com läuft und über eine öffentliche URL (z.B. `https://arzttarif-assistent.onrender.com`) erreichbar ist, hast du mehrere Möglichkeiten zur Integration:

*   **Einfacher Link:** Du kannst einfach einen Link von arkons.ch auf die Render.com-URL setzen.
    ```html
    <a href="https://arzttarif-assistent.onrender.com" target="_blank">Zum TARDOC/Pauschalen Assistent</a>
    ```
*   **iFrame:** Du kannst den Assistenten als iFrame in eine Seite auf arkons.ch einbetten.
    ```html
    <iframe src="https://arzttarif-assistent.onrender.com" width="100%" height="800px" style="border:none;"></iframe>
    ```
    Beachte, dass iFrames manchmal Einschränkungen bezüglich Styling und Interaktion haben können. Stelle sicher, dass deine Anwendung so gestaltet ist, dass sie gut in einem iFrame funktioniert.
*   **Custom Domain (Empfohlen für professionelles Aussehen):**
    Du kannst auf Render.com eine Custom Domain für deinen Web Service konfigurieren (z.B. `assistent.arkons.ch`). Dafür musst du DNS-Einträge bei deinem Domain-Registrar (wo arkons.ch gehostet wird) anpassen. Render.com stellt dafür Anleitungen bereit. Dies ist die sauberste Methode für eine nahtlose Integration.
*   **Reverse Proxy (Fortgeschritten):** Wenn arkons.ch auf einem eigenen Server läuft, könntest du einen Reverse Proxy (z.B. mit Nginx oder Apache) einrichten, der Anfragen an z.B. `arkons.ch/assistent` intern an deine Render.com-Anwendung weiterleitet. Das erfordert Serverkonfiguration.

Für die meisten Anwendungsfälle ist eine **Custom Domain** die beste Lösung für eine professionelle Integration. Ein einfacher Link oder iFrame ist für den Anfang auch möglich.