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
6.  Integration in deine Webseite (arkons.ch via Localsearch)

---

**1. Projektübersicht**

Der "TARDOC und Pauschalen Assistent" ist eine Webanwendung, die medizinische Leistungstexte analysiert und basierend auf dem Schweizer Arzttarif (TARDOC und Pauschalen) Vorschläge zur Abrechnung generiert. Die Anwendung nutzt eine Kombination aus lokalen Daten und Regelwerken sowie einer externen KI-API (Google Gemini) für die Textanalyse.

**Architektur:**

*   **Backend:** Flask (Python) Anwendung (`server.py`), die die Hauptlogik, Datenverarbeitung und API-Aufrufe handhabt. Wird mit Gunicorn betrieben.
*   **Frontend:** HTML, CSS und JavaScript (`index.html`, `calculator.js`) für die Benutzeroberfläche.
*   **Daten:** Lokale JSON-Dateien im `./data`-Verzeichnis, verwaltet mit Git LFS.
*   **KI-Service:** Google Gemini API für die Verarbeitung von Freitext-Eingaben.
*   **Datenlade-Hook:** `gunicorn_config.py` stellt sicher, dass Daten beim Start jedes Gunicorn-Workers geladen werden.

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
Die Datei `requirements.txt` im Stammverzeichnis deines Projekts sollte folgenden Inhalt haben:
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
GEMINI_MODEL="gemini-1.5-flash-latest" # Oder dein bevorzugtes Modell, z.B. gemini-1.5-pro-latest
```
Ersetze `DEIN_TATSÄCHLICHER_GEMINI_API_KEY` durch deinen Schlüssel. Es ist wichtig, `GEMINI_MODEL` hier (und auf Render.com) konsistent zu halten, da unterschiedliche Modelle leicht abweichendes Verhalten zeigen können.

**3.6. Daten laden (Initial)**
Der Python-Server (`server.py`) enthält eine `load_data()`-Funktion. Diese wird lokal beim direkten Start von `server.py` aufgerufen und auf Render.com durch den Gunicorn-Hook in `gunicorn_config.py` beim Start der Worker. Stelle sicher, dass das `data`-Verzeichnis mit allen benötigten JSON-Dateien vorhanden ist.

**3.7. Anwendung lokal starten**
Führe das Backend aus:
```bash
python server.py
```
Der Server sollte starten (standardmäßig auf `http://127.0.0.1:8000`). Öffne diese Adresse in deinem Webbrowser, um die Anwendung zu sehen. Die Konsole zeigt Log-Ausgaben, inklusive des Datenladevorgangs.

**4. Deployment auf Render.com**

**4.1. Vorbereitung des Git-Repositories**
1.  **`.gitignore`:** Stelle sicher, dass `.env`, `__pycache__/`, `*.pyc` und andere lokale/sensible Dateien in deiner `.gitignore`-Datei aufgeführt sind.
2.  **`requirements.txt`:** Muss wie oben beschrieben vorhanden sein.
3.  **`gunicorn_config.py`:** Diese Datei ist für das korrekte Laden der Daten in jeder Worker-Instanz auf Render.com zuständig. Stelle sicher, dass sie im Stammverzeichnis deines Repositories liegt und korrekt funktioniert.
4.  **`Procfile`:** Erstelle eine Datei namens `Procfile` (ohne Dateiendung) im Stammverzeichnis mit folgendem Inhalt:
    ```Procfile
    web: gunicorn -c gunicorn_config.py server:app --timeout 120
    ```
    *   `server:app` geht davon aus, dass deine Flask-App-Instanz in `server.py` den Namen `app` hat.
    *   `-c gunicorn_config.py` weist Gunicorn an, deine Konfigurationsdatei zu verwenden.
    *   `--timeout 120` erhöht das Timeout für Worker auf 120 Sekunden.
5.  **Git LFS:** Stelle sicher, dass `.gitattributes` committet ist und du deine Änderungen (inklusive der LFS-Pointer und der `gunicorn_config.py` sowie `Procfile`) zu deinem Git-Provider (z.B. GitHub) gepusht hast.

**4.2. Neuen Web Service auf Render.com erstellen**
1.  Logge dich in dein Render.com Dashboard ein.
2.  Klicke auf "New +" und wähle "Web Service".
3.  Verbinde dein Git-Repository (z.B. GitHub). Wähle das korrekte Repository aus.

**4.3. Konfiguration auf Render.com**
Fülle die Felder wie folgt aus:

*   **Name:** Ein eindeutiger Name für deinen Service (z.B. `arzttarif-assistent`).
*   **Region:** Wähle eine passende Region (z.B. "Frankfurt (EU Central)").
*   **Branch:** Der Branch, der deployed werden soll (z.B. `master` oder `main`).
*   **Root Directory:** Leer lassen (wenn sich `requirements.txt`, `Procfile` etc. im Stammverzeichnis befinden).
*   **Runtime/Language:** Sollte automatisch als "Python" erkannt werden.
*   **Build Command:**
    ```bash
    pip install -r requirements.txt
    ```
*   **Start Command:**
    Render.com sollte den Startbefehl aus deiner `Procfile` (`gunicorn -c gunicorn_config.py server:app --timeout 120`) automatisch erkennen und verwenden. Du kannst es hier zur Sicherheit auch explizit eintragen.
*   **Instance Type:** Wähle einen passenden Plan (z.B. "Free" zum Testen, später ggf. upgraden).
*   **Environment Variables:**
    *   Klicke auf "Add Environment Variable" oder "Add Secret File" für den API Key.
    *   **Key:** `GEMINI_API_KEY`, **Value:** `DEIN_TATSÄCHLICHER_GEMINI_API_KEY`
    *   **Key:** `GEMINI_MODEL`, **Value:** `gemini-1.5-flash-latest` (oder das Modell, das du konsistent verwenden möchtest, z.B. `gemini-1.5-pro-latest`. **Wichtig:** Halte dies konsistent mit deiner lokalen `.env`-Datei, um unterschiedliches LLM-Verhalten zu minimieren.)
    *   (Optional) **Key:** `PYTHON_VERSION`, **Value:** `3.11.4` (oder deine spezifische Python-Version, die Render.com verwenden soll).

**4.4. Deployment und Überprüfung**
1.  Klicke auf "Create Web Service".
2.  Render.com wird nun dein Repository klonen (inklusive Auflösung der Git LFS-Dateien), die Abhängigkeiten installieren und die Anwendung gemäß deiner `Procfile` starten.
3.  Du kannst den Fortschritt im "Events"-Tab und die Logs im "Logs"-Tab verfolgen. Achte hier besonders auf die Ausgaben von `gunicorn_config.py` bezüglich des Datenladens.
4.  Nach erfolgreichem Deployment stellt Render.com dir eine URL zur Verfügung (z.B. `https://arzttarif-assistent.onrender.com`). Rufe diese URL im Browser auf, um deine Anwendung zu testen.

**5. Betrieb und Wartung**

*   **Datenaktualisierung:**
    *   Wenn du die JSON-Dateien im `./data`-Verzeichnis aktualisierst:
        1.  Füge die geänderten Dateien zu Git hinzu (`git add data/deine_datei.json`).
        2.  Committe die Änderungen (`git commit -m "Datenaktualisierung für XYZ"`).
        3.  Pushe die Änderungen zu deinem Git-Provider (`git push`).
        4.  Render.com sollte (je nach Einstellung für "Auto-Deploy") automatisch ein neues Deployment mit den aktualisierten Daten starten. Die `gunicorn_config.py` sorgt dafür, dass die neuen Daten von den Workern geladen werden.
*   **Log-Überwachung:** Überprüfe regelmäßig die Logs deiner Anwendung auf Render.com ("Logs"-Tab), um Fehler oder unerwartetes Verhalten zu erkennen, insbesondere nach Änderungen oder bei gemeldeten Problemen.
*   **Abhängigkeiten aktualisieren:** Halte deine `requirements.txt` aktuell und deploye neu, wenn du Bibliotheken aktualisierst.

**6. Integration in deine Webseite (arkons.ch via Localsearch)**

Dein Assistent ist auf Render.com unter einer URL wie `https://arzttarif-assistent.onrender.com` (ersetze dies mit deiner tatsächlichen Render-URL) erreichbar. Für die Integration in deine arkons.ch-Webseite, die über Localsearch (`mywebsite.localsearch.ch`) verwaltet wird, ist die gängigste Methode die Einbettung mittels eines **iFrames**.

Deine spezifische Seite für den Assistenten ist:
`https://mywebsite.localsearch.ch/home/site/6feb9afb9e5240df962f60f1082e85a0/assistent--neuer-arzttarif-ab-2026`

**Schritte zur Integration über Localsearch (Allgemein):**

1.  **Localsearch Website-Editor öffnen:** Logge dich in das Backend deines Localsearch Website-Builders ein.
2.  **Seite bearbeiten:** Navigiere zu der Seite, auf der der Assistent angezeigt werden soll (die oben genannte URL).
3.  **HTML/Embed-Widget hinzufügen:** Die meisten Website-Builder bieten ein Widget oder Element an, um eigenen HTML-Code oder eine externe Webseite einzubetten (oft "HTML-Code", "Embed", "iFrame" oder ähnlich genannt). Füge ein solches Element an der gewünschten Stelle auf deiner Seite ein.
4.  **iFrame-Code einfügen:** In das HTML/Embed-Widget fügst du den folgenden iFrame-Code ein, wobei du `DEINE_RENDER_APP_URL` durch die tatsächliche URL deiner auf Render.com gehosteten Anwendung ersetzt:

    ```html
    <iframe 
        src="DEINE_RENDER_APP_URL" 
        width="100%" 
        height="1000px" 
        style="border:none;"
        title="TARDOC und Pauschalen Assistent">
    </iframe>
    ```
    *   **`src`**: Ersetze `DEINE_RENDER_APP_URL` mit der URL deiner Anwendung auf Render.com (z.B. `https://arzttarif-assistent.onrender.com`).
    *   **`width="100%"`**: Lässt den iFrame die volle Breite des verfügbaren Containers einnehmen.
    *   **`height="1000px"`**: Setzt eine feste Höhe. Du musst diesen Wert eventuell anpassen, damit der gesamte Inhalt des Assistenten ohne Scrollbalken *im iFrame* sichtbar ist, oder zumindest eine angenehme Starthöhe hat. Teste dies auf verschiedenen Bildschirmgrößen.
    *   **`style="border:none;"`**: Entfernt den Standardrahmen des iFrames.
    *   **`title`**: Wichtig für Barrierefreiheit.

5.  **Speichern und Veröffentlichen:** Speichere die Änderungen in deinem Localsearch-Editor und veröffentliche deine Webseite neu.
6.  **Testen:** Überprüfe die Seite `https://mywebsite.localsearch.ch/.../assistent--neuer-arzttarif-ab-2026` auf verschiedenen Geräten, um sicherzustellen, dass der Assistent korrekt angezeigt wird und benutzbar ist. Achte auf doppelte Scrollbalken (einer vom Browser, einer vom iFrame) und passe die `height` des iFrames bei Bedarf an.

**Alternative Integrationsmethoden (Allgemein):**

*   **Einfacher Link:** Du könntest auch einfach einen prominenten Link von deiner arkons.ch-Seite auf die Render.com-URL des Assistenten setzen. Dies ist die einfachste Methode, aber der Benutzer verlässt dann deine Hauptseite.
    ```html
    <a href="DEINE_RENDER_APP_URL" target="_blank">Zum TARDOC & Pauschalen Assistenten</a>
    ```
*   **Custom Domain für die Render-App (Fortgeschritten):** Für ein professionelleres Aussehen könntest du deiner Render-App eine Subdomain deiner Hauptdomain zuweisen (z.B. `assistent.arkons.ch`). Dies erfordert DNS-Anpassungen bei deinem Domain-Registrar und die Konfiguration der Custom Domain in Render.com. Anschließend könntest du diese Custom Domain im iFrame verwenden oder direkt darauf verlinken.

Für die Einbindung über Plattformen wie Localsearch ist der iFrame-Ansatz in der Regel der praktikabelste Weg, um externe Anwendungen darzustellen.