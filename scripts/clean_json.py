"""Hilfsfunktionen zum Säubern von JSON-Dateien im OAAT-Projekt.

Die Funktion :func:`clean_file` entfernt störende Steuerzeichen aus einer
JSON-Datei, damit nachgelagerte Werkzeuge sie fehlerfrei parsen können. Bei
direktem Aufruf erwartet das Modul einen Dateipfad, bereinigt die Datei und
schreibt eine Kopie mit der Endung ``.clean.json`` neben die ursprüngliche
Datei. Das Skript eignet sich für Fremdimporte, die z.B. ``\x00`` oder
``\x1A`` enthalten.
"""

import json
from pathlib import Path

def clean_file(path: Path) -> Path:
    """Remove ASCII control characters from JSON file and return path to cleaned file."""
    data = path.read_bytes()
    cleaned = bytes(c for c in data if c >= 32 or c in b"\n\t\r")
    cleaned_path = path.with_suffix('.clean.json')
    # Originaldatei bleibt unverändert, die bereinigte Kopie liegt direkt daneben.
    cleaned_path.write_bytes(cleaned)
    return cleaned_path

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Clean control characters from JSON")
    parser.add_argument('file', type=Path)
    args = parser.parse_args()
    clean_file(args.file)
