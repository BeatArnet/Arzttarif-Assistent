# TARDOC Tarifziffern-Erkenner

Dieser verbesserte TARDOC Tarifziffern-Erkenner verwendet einen hybriden Ansatz, um medizinische Leistungen zu analysieren und die entsprechenden Tarifziffern zu identifizieren.

## Funktionsweise

Der Erkenner kombiniert drei Methoden:
1. **Regelbasierte Erkennung** mit Mapping-Tabellen für häufige Eingriffe
2. **Keyword-basierte Extraktion** für strukturierte Informationen
3. **Semantische Suche** als Fallback für komplexere Fälle

## Dateien

- **hybrid_recognizer.py**: Implementierung des Hybrid-Erkenners
- **medical_mappings.json**: Mapping-Tabellen für häufige Eingriffe
- **server_integration.py**: Integration in den bestehenden Server
- **DOCUMENTATION.md**: Ausführliche Dokumentation der Änderungen

## Installation

1. Stellen Sie sicher, dass alle Dateien im Projektverzeichnis vorhanden sind
2. Integrieren Sie den Hybrid-Erkenner in Ihren Server:

```python
from hybrid_recognizer import HybridRecognizer
from server_integration import integrate_hybrid_recognizer

# Hybrid-Erkenner in den Server integrieren
integrate_hybrid_recognizer(app, server_module)
```

## Beispiel

Für die Eingabe "Entfernung Warze am Oberkörper mit scharfem Löffel und 10 Minuten Information Patienten" liefert der Erkenner:

```
Erkannte Tarifziffern:
  AA.00.0010 1x
  AA.00.0020 5x
  MK.05.0070 1x
```

## Erweiterung

Die Mapping-Tabellen können leicht um weitere medizinische Eingriffe erweitert werden, indem neue Einträge in der Datei `medical_mappings.json` hinzugefügt werden.
