import json
from pathlib import Path

def clean_file(path: Path) -> Path:
    """Remove ASCII control characters from JSON file and return path to cleaned file."""
    data = path.read_bytes()
    cleaned = bytes(c for c in data if c >= 32 or c in b"\n\t\r")
    cleaned_path = path.with_suffix('.clean.json')
    cleaned_path.write_bytes(cleaned)
    return cleaned_path

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Clean control characters from JSON")
    parser.add_argument('file', type=Path)
    args = parser.parse_args()
    clean_file(args.file)
