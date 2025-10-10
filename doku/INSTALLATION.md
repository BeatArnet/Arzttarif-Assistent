# Installations- und Betriebsdokumentation: Arzttarif-Assistent

Dieses Dokument beschreibt die Einrichtung, das Deployment und den Betrieb des "Arzttarif-Assistenten", sowohl für die lokale Entwicklung als auch für den produktiven Einsatz auf einer Plattform wie Render.com.

Aktuelle Version: 3.4 (siehe `config.ini` oder Endpoint `/api/version`).
Ausführliche Änderungen: siehe `CHANGELOG.md`.

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
*   **KI-Service:** Konfigurierbar (z. B. SwissAI/Apertus – OpenAI‑kompatibel, Google Gemini, OpenAI, Ollama‑Gateway).

## 2. Voraussetzungen

*   **Lokal:**
    *   Python (Version 3.9 oder höher)
    *   `pip` (Python Package Installer)
    *   Git
    *   Ein API‑Key für den gewünschten LLM‑Provider (z. B. `GEMINI_API_KEY`, `OPENAI_API_KEY`, `APERTUS_API_KEY`).
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
Wenn der optionale RAG-Modus aktiviert werden soll, installiere zusätzlich
`sentence-transformers` und erstelle anschliessend die Embedding-Datei:
```bash
pip install sentence-transformers
python generate_embeddings.py
```
Ohne RAG müssen beim LLM mehr als 600 000 Tokens verarbeitet werden. Durch die
Embedding-Suche sinkt der Bedarf auf rund 10 000 Tokens pro Anfrage.

**3.5. Synonymverwaltung aktualisieren (optional)**
Um Synonyme zu erweitern oder neu zu generieren, steht das Paket im
Verzeichnis `synonyms/` zur Verfügung. Starte den GUI‑Editor mit:
```bash
python -m synonyms
```
Nach Änderungen muss der Server neu gestartet und – falls der RAG‑Modus aktiv ist – die
Embeddings neu erstellt werden.

**3.6. Umgebungsvariablen konfigurieren**
Erstelle eine Datei namens `.env` im Projektstammverzeichnis (diese Datei wird durch `.gitignore` ignoriert). Typische Variablen:
```env
# LLM-Provider (nur die benötigten setzen)
GEMINI_API_KEY="..."
OPENAI_API_KEY="..."
APERTUS_API_KEY="..."
APERTUS_BASE_URL="https://api.publicai.co/v1"    # optional, falls abweichend
OLLAMA_BASE_URL="http://localhost:11434/v1"      # optional für OpenAI-kompatibles Gateway

# Synonym-Generator (falls externer Provider genutzt werden soll)
SYNONYM_LLM_API_KEY="..."
SYNONYM_LLM_MODEL="gemini-2.5-flash"

# Optional: Feedback → GitHub-Issues
GITHUB_TOKEN="..."
GITHUB_REPO="USER/REPO"
```
Weitere relevante Konfigurationsoptionen ab Version 3.1+
- Getrennte Temperatur-Parameter für Stage 2: `stage2_mapping_temperature`, `stage2_ranking_temperature`.
- Granulares Logging unter `[LOGGING]` (z. B. `log_llm_input`, `log_llm_prompt`, `log_llm_output`, `log_tokens`).
- Tokenbudgets/Trimming:
  - `[OPENAI]`: `token_budget_default`, `token_budget_apertus`, `trim_apertus_enabled`, `trim_max_passes`.
  - `[GEMINI]`: `token_budget`, `trim_enabled`.
Die Zuordnung des LLMs erfolgt in `config.ini` unter `[LLM1UND2]` über `stage1_provider/_model` und `stage2_provider/_model`. Für den Synonym‑Editor wird der Provider in `[SYNONYMS]` festgelegt (`llm_provider`, `llm_model`).

**3.7. Anwendung lokal starten**
```bash
python server.py
```
Der Server startet standardmässig auf `http://127.0.0.1:8000`.

**3.8. LLM-Vergleich durchführen (optional)**
In `llm_vergleich_results.json` lassen sich verschiedene Modelle definieren,
die mit `llm_vergleich.py` automatisch gegen die Beispiele aus
`data/baseline_results.json` getestet werden. Für jede Stufe kann ein eigener
Provider und ein eigenes Modell (`Stage1Provider`/`Stage1Model` bzw.
`Stage2Provider`/`Stage2Model`) angegeben werden; ansonsten gelten `Provider`
und `Model` für beide Stufen. Das Skript schreibt Korrektheit, Laufzeit und
Tokenverbrauch pro Konfiguration zurück in die JSON.

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
5.  **Environment Variables:** Füge den API‑Key des gewählten Providers (z. B. `APERTUS_API_KEY`, `GEMINI_API_KEY`, `OPENAI_API_KEY`) hinzu und passe `config.ini` an.

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
