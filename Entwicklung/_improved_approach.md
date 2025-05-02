# Verbesserter Ansatz für die Tarifziffern-Erkennung

## Konzeptionelle Änderungen

### 1. Hybrides Erkennungssystem
Statt sich ausschließlich auf semantische Suche zu verlassen, sollte ein hybrides System implementiert werden:
- **Regelbasierte Erkennung**: Direkte Zuordnung häufiger medizinischer Eingriffe zu Tarifziffern
- **Semantische Suche**: Als Fallback für komplexere oder seltenere Fälle
- **Keyword-basierte Erkennung**: Extraktion spezifischer Schlüsselwörter und deren Zuordnung zu Tarifziffern

### 2. Strukturierte Informationsextraktion
- Systematische Extraktion von relevanten Informationen aus der Eingabe:
  - Art des Eingriffs (z.B. "Entfernung", "Konsultation")
  - Körperregion (z.B. "Oberkörper", "Stamm")
  - Methode (z.B. "mit scharfem Löffel")
  - Zeitdauer (z.B. "10 Minuten")
  - Patienteninformationen (Alter, Geschlecht)

### 3. Verbesserte LLM-Prompts
- Spezifischere Anweisungen für das LLM, um gezielt nach Tarifziffern zu suchen
- Beispiele für erwartete Ausgaben in den Prompt integrieren
- Explizite Anweisung, die Tarifziffern im Format "XX.XX.XXXX" zu identifizieren

### 4. Mapping-Tabellen
- Erstellung von direkten Mapping-Tabellen für häufige medizinische Eingriffe
- Beispiel: "Entfernung Warze" → AA.00.0010, AA.00.0020, MK.05.0070
- Diese Tabellen können als JSON-Dateien gespeichert und bei Bedarf erweitert werden

## Technische Implementierung

### 1. Datenstruktur erstellen
- Erstellung der fehlenden JSON-Dateien mit Beispieldaten
- Implementierung einer Struktur für direkte Mappings häufiger Eingriffe

### 2. Verbesserte Vorverarbeitung
- Implementierung einer robusteren Vorverarbeitung der Eingabetexte
- Extraktion von Schlüsselwörtern und Kategorisierung nach Art des Eingriffs, Körperregion, etc.

### 3. Mehrstufiger Erkennungsprozess
1. **Direkte Mapping-Prüfung**: Überprüfung, ob der Eingriff direkt in den Mapping-Tabellen vorhanden ist
2. **Regelbasierte Erkennung**: Anwendung von Regeln basierend auf extrahierten Informationen
3. **Semantische Suche**: Nur als Fallback, wenn die vorherigen Schritte keine Ergebnisse liefern

### 4. Verbesserter LLM-Prompt
```
Analysiere den folgenden medizinischen Behandlungstext und identifiziere die entsprechenden TARDOC-Tarifziffern.

Beispiel:
Text: "Entfernung Warze am Oberkörper mit scharfem Löffel und 10 Minuten Information Patienten"
Erwartete Tarifziffern: AA.00.0010 1x, AA.00.0020 5x, MK.05.0070 1x

--- Relevante TARDOC-Zeilen ---
{ctx}
--- Ende ---

Gib ausschließlich JSON nach Schema:
{schema}

Text: '{text}'

JSON-Antwort:
```

### 5. Feedback-Mechanismus
- Implementierung eines Feedback-Mechanismus, der es Benutzern ermöglicht, falsche oder fehlende Tarifziffern zu melden
- Diese Informationen können zur kontinuierlichen Verbesserung des Systems verwendet werden

## Beispiel-Mapping für häufige Eingriffe

```json
{
  "entfernung_warze": {
    "tarifziffern": [
      {"code": "AA.00.0010", "beschreibung": "Konsultation, erste 5 Min.", "menge": 1},
      {"code": "AA.00.0020", "beschreibung": "Konsultation, jede weiteren 5 Min.", "menge": 5},
      {"code": "MK.05.0070", "beschreibung": "Entfernung oberflächlicher Hautveränderung", "menge": 1}
    ],
    "varianten": ["warze", "hautveränderung", "hautläsion"],
    "körperregionen": ["oberkörper", "stamm", "rücken", "brust"],
    "methoden": ["scharfer löffel", "kürettage", "exzision"]
  },
  "hausärztliche_konsultation": {
    "tarifziffern": [
      {"code": "AA.00.0010", "beschreibung": "Konsultation, erste 5 Min.", "menge": 1},
      {"code": "AA.00.0020", "beschreibung": "Konsultation, jede weiteren 5 Min.", "menge": "DAUER_IN_MIN / 5"}
    ],
    "varianten": ["konsultation", "beratung", "untersuchung"],
    "zusatz": ["hausarzt", "hausärztlich", "allgemeinmedizin"]
  }
}
```

## Implementierungsplan

1. **Datenstruktur erstellen**: Erstellung der notwendigen JSON-Dateien mit Beispieldaten
2. **Mapping-Tabellen implementieren**: Erstellung von Mapping-Tabellen für häufige medizinische Eingriffe
3. **Vorverarbeitung verbessern**: Implementierung einer robusteren Vorverarbeitung der Eingabetexte
4. **Mehrstufigen Erkennungsprozess implementieren**: Integration der verschiedenen Erkennungsmethoden
5. **LLM-Prompt verbessern**: Anpassung des Prompts für bessere Tarifziffern-Erkennung
6. **Feedback-Mechanismus implementieren**: Möglichkeit für Benutzer, Feedback zu geben
7. **Testen und Optimieren**: Umfangreiche Tests mit verschiedenen Eingaben und Optimierung des Systems
