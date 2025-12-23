# Anwendung des Arzttarif-Assistenten

Diese Kurzanleitung richtet sich an alle Nutzenden, die den Arzttarif-Assistenten ausprobieren möchten. Sie zeigt die typischen Arbeitsschritte, gibt Hinweise zur iterativen Nutzung und beschreibt die Grenzen des Systems.

Hinweis Version 4.6
- CHF-Betrag wird nun direkt aus den hinterlegten Taxpunktwerten je Kanton und Sozialversicherungsbereich berechnet und im UI ausgewiesen.
- Suche & Trefferqualität: Stage 1 kombiniert direkte LKN-Erkennung, gewichtete Schlüsselwortsuche und Embedding-Ranking. Alter/Geschlecht werden automatisch aus dem Freitext erkannt und fließen in die Kandidatenliste ein; Zuschläge für Kinder oder geschlechtsspezifische Leistungen werden dadurch zuverlässiger gefunden.
- Ergebnisdetails: Die LLM-Details zeigen eine gerankte Kandidatenliste, Kontextzeilen enthalten Demografie-Hinweise zu TARDOC-Positionen.
- Geschwindigkeit & QS: Pauschalen-Checks laufen schneller durch vorindizierte Regeln. Die Qualitätskontrolle zeigt Laufzeiten/Token (Ø/Median/p95/Max) und umfasst zusätzliche Referenzfälle.

## 1. Voraussetzungen und Start

1. Installieren Sie die Abhängigkeiten gemäss `INSTALLATION.md` und legen Sie – je nach gewähltem Provider – den passenden API‑Schlüssel (z. B. `GEMINI_API_KEY`, `OPENAI_API_KEY`, `APERTUS_API_KEY`) in einer `.env`-Datei ab.
2. Optional: Soll der RAG-Modus genutzt werden, setzen Sie in `config.ini` unter `[RAG]` den Wert `enabled = 1` und erzeugen Sie zuvor die Datei `data/leistungskatalog_embeddings.json` mit `python generate_embeddings.py` (benötigt `sentence-transformers`).
3. Starten Sie den Server lokal mit:
   ```bash
   python server.py
   ```
   Anschliessend erreichen Sie die Weboberfläche unter [http://127.0.0.1:8000].

## 2. Erste Schritte in der Weboberfläche

1. Wählen Sie bei Bedarf die Sprache (Deutsch, Französisch oder Italienisch).
2. Optional können Sie über die Dropdown-Liste ein Beispiel laden, um die Funktionsweise kennenzulernen.
3. Tragen Sie die **Leistungsbeschreibung oder LKN** ins Textfeld ein. Zusätzliche Angaben wie Dauer, Alter oder Geschlecht können das Ergebnis verbessern.
4. Bei Bedarf können Sie auch einen **ICD-Code**, **GTINs** oder einen **CHOP-Code** angeben. Mit dem Häkchen "ICD berücksichtigen" steuern Sie, ob ICD-Regeln für Pauschalen angewendet werden sollen.
5. Klicken Sie auf **"Tarifpositionen finden"**. Das Resultat erscheint nach kurzer Zeit im unteren Bereich.

## 3. Iteratives Vorgehen

Der Assistent verwendet ein konfigurierbares KI‑Modell (z. B. Gemini, OpenAI oder SwissAI/Apertus) in Kombination mit lokalen Regeln. Schon kleine Anpassungen im Freitext können zu anderen Vorschlägen führen. Gehen Sie daher schrittweise vor:

1. **Kurzbeschreibung testen:** Beginnen Sie mit einer einfachen Beschreibung der Leistung. Notieren Sie sich das Ergebnis.
2. **Weitere Details hinzufügen:** Fügen Sie bei Bedarf Angaben zu Zeitdauer, Körperregion, Material oder Diagnosen hinzu. Wiederholen Sie die Analyse und vergleichen Sie die Resultate.
3. **Synonyme ausprobieren:** Verschiedene Formulierungen oder ein geänderter Satzbau können andere LKNs oder Pauschalen hervorbringen.
4. **Qualitätskontrolle nutzen:** Unter dem Link "Qualitätskontrolle" (bzw. `quality.html`) finden Sie vordefinierte Beispiele, mit denen Sie das System testen können.

Durch dieses iterative Vorgehen können Sie herausfinden, welche Angaben den gewünschten Effekt haben.

## 4. Grenzen der Anwendung

* **Ohne Gewähr:** Der Arzttarif-Assistent ist ein Open-Source-Prototyp. Die Resultate können Fehler enthalten und sind nicht verbindlich.
* **Offizielle Quellen benutzen:** Für rechtsgültige Tarifinformationen konsultieren Sie den [OAAT Tarifbrowser](https://tarifbrowser.oaat-otma.ch/startPortal) oder die [Tarifplattform der FMH](https://www.tarifeambulant.fmh.ch/).
* **Keine persönlichen Daten eingeben:** Die KI-Abfragen laufen über Google Gemini. Geben Sie daher keine patientenbezogenen Daten ein.
* **Tokenbedarf:** Ohne RAG werden sämtliche Katalogdaten an das LLM gesendet (mehr als 600 000 Tokens). Mit aktiviertem RAG werden nur die relevantesten Einträge übermittelt (ca. 10 000 Tokens).
* **Unvollständige Datenbasis:** Die bereitgestellten JSON-Dateien und Regeln können Lücken enthalten. Spezielle Fälle oder neue Tarifpositionen sind möglicherweise nicht abgedeckt.
* **Manuelle Prüfung erforderlich:** Die Vorschläge des Assistenten ersetzen nicht die finale fachliche Beurteilung. Kontrollieren Sie die Resultate und vergleichen Sie sie mit den offiziellen Angaben.
* **Synonymliste abhängig vom Datenstand:** Die verwendeten Synonyme stammen aus dem Leistungskatalog `LKAAT_Leistungskatalog.json`. Bei einer neuen Version der Tarifdaten müssen Synonymtabelle und Embeddings neu erzeugt werden, sonst werden neue Begriffe eventuell nicht erkannt.

## 5. Tipps für erfahrene Nutzende

* **Patientenkontext nutzen:** Alter oder Geschlecht können im Freitext oder in den Formularfeldern stehen – die App erkennt beides und priorisiert alters-/geschlechtsspezifische Zuschläge automatisch.
* **CHOP- und ICD-Suche:** Über die Felder für CHOP-Code und ICD können Sie direkt nach Eingriffen bzw. Diagnosen suchen und diese in die Analyse einbeziehen.
* **Ergebnisse nachvollziehen:** Der Assistent zeigt bei Pauschalen die geprüften Bedingungen an. Bei TARDOC-Einzelleistungen werden die relevanten Regeln mitgeliefert. Nutzen Sie diese Informationen, um die Entscheidung nachzuvollziehen.
* **Feedback-Funktion:** Falls Sie Verbesserungswünsche haben, können Sie über den Button "Feedback geben" eine kurze Nachricht senden.

## 6. Synonymverwaltung

Der Assistent nutzt eine Synonymliste, um unterschiedliche Formulierungen
derselben Leistung zu erkennen. Die Datei `data/synonyms.json` wird beim
Start automatisch geladen. Eigene Einträge können mit dem GUI‑Werkzeug gestartet via
`python -m synonyms` ergänzt/kuratiert werden. Nach Änderungen muss der
Server neu gestartet werden.

## 7. Vergleich verschiedener LLMs

Zur Bewertung alternativer Sprachmodelle steht das Skript
`llm_vergleich.py` zur Verfügung. Es führt die Testbeispiele aus
`data/baseline_results.json` für jede in `llm_vergleich_results.json`
definierte Konfiguration aus. Dort kann pro Stufe ein eigener Provider und ein
eigenes Modell angegeben werden; andernfalls gelten `Provider` und `Model` für
beide Stufen. Das Skript protokolliert Korrektheit, Laufzeit sowie den
Tokenverbrauch und ermöglicht so den Vergleich verschiedener Anbieter.

## 8. RAG-Modus

Mit aktiviertem RAG-Modus werden vor einer Anfrage die passendsten
Leistungskatalogeinträge per Vektor-Suche ermittelt und an das LLM
übermittelt. Die Embeddings erzeugen Sie einmalig mit
`python generate_embeddings.py`; in `config.ini` wird der Modus über den
Abschnitt `[RAG]` gesteuert.

---

Mit dieser Anleitung sollten sowohl Einsteiger als auch versierte User den Arzttarif-Assistenten effizient nutzen können. Beachten Sie stets die genannten Grenzen und ziehen Sie bei Unsicherheiten die offiziellen Quellen zu Rate.

