# Probleme und Einschränkungen der aktuellen Implementierung

## 1. Fehlende Datendateien
- Die notwendigen JSON-Dateien fehlen im data-Verzeichnis
- Ohne diese Dateien kann die semantische Suche nicht funktionieren
- Benötigte Dateien laut Code:
  - tblLeistungskatalog.json
  - tblPauschaleLeistungsposition.json
  - tblPauschalen.json
  - tblPauschaleBedingungen.json
  - TARDOCGesamt_optimiert_Tarifpositionen.json
  - tblTabellen.json
  - strukturierte_regeln_komplett.json (für regelpruefer.py)

## 2. Konzeptionelle Probleme bei der semantischen Suche
- Die aktuelle Implementierung verlässt sich stark auf semantische Ähnlichkeit
- Bei spezifischen medizinischen Eingriffen wie "Entfernung Warze am Oberkörper mit scharfem Löffel" kann die semantische Suche unzureichend sein
- Der Code verwendet zwar eine Fallback-Substring-Suche, aber diese scheint nicht effektiv zu sein

## 3. LLM-Prompt-Probleme
- Der Prompt für das LLM ist möglicherweise nicht spezifisch genug
- Es fehlt eine klare Anweisung, nach konkreten Tarifziffern zu suchen
- Das LLM wird nicht explizit angewiesen, die erwarteten Tarifziffern (wie AA.00.0010, AA.00.0020, MK.05.0070) zu identifizieren

## 4. Fehlende Regelbasierte Komponente
- Die Anwendung verlässt sich zu stark auf semantische Suche und LLM
- Es fehlt eine regelbasierte Komponente, die spezifische medizinische Eingriffe direkt mit Tarifziffern verknüpft
- Beispielsweise sollte "Entfernung Warze" direkt mit bestimmten Tarifziffern assoziiert werden

## 5. Unzureichende Extraktion von Informationen
- Die Extraktion von Informationen wie Dauer, Körperregion und Verfahren scheint unzureichend zu sein
- Diese Informationen sind jedoch entscheidend für die korrekte Zuordnung von Tarifziffern

## 6. Fehlende Validierung und Feedback
- Es gibt keine Möglichkeit für Benutzer, Feedback zu geben, wenn falsche oder keine Tarifziffern gefunden werden
- Ein Lernmechanismus, der aus Benutzerfeedback lernt, fehlt

## 7. Unzureichende Dokumentation
- Die Dokumentation der erwarteten Eingabeformate und der unterstützten medizinischen Leistungen ist unzureichend
- Benutzer wissen möglicherweise nicht, wie sie ihre Anfragen formulieren sollen, um optimale Ergebnisse zu erzielen

## 8. Fehlende Beispiele und Templates
- Es fehlen vordefinierte Beispiele oder Templates für häufige medizinische Leistungen
- Diese könnten als Ausgangspunkt für Benutzer dienen und die Genauigkeit verbessern

## 9. Keine Berücksichtigung von Kontext
- Die Anwendung berücksichtigt nicht den Kontext mehrerer medizinischer Leistungen in einer Sitzung
- In der Realität werden oft mehrere Leistungen kombiniert, was Auswirkungen auf die Tarifziffern haben kann
