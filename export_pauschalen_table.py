import json
from pathlib import Path
from typing import Any, List, Dict


def _decode_numeric_field(value: Any) -> Any:
    """Convert byte-like strings ("\x01\x00\x00\x00") to integers."""
    if isinstance(value, str) and len(value) == 4 and all(ord(c) < 32 for c in value):
        try:
            return int.from_bytes(value.encode('latin-1'), 'little')
        except Exception:
            return value
    return value


def export_pauschalen_table(in_path: Path, out_path: Path) -> List[Dict[str, Any]]:
    """Load JSON from ``in_path`` and write cleaned list to ``out_path``.

    The function converts binary string representations in the ``Ebene`` and
    ``Gruppe`` fields to integers. It returns the cleaned list of dictionaries.
    """
    with in_path.open('r', encoding='utf-8') as f:
        data = json.load(f)

    for entry in data:
        if isinstance(entry, dict):
            entry['Ebene'] = _decode_numeric_field(entry.get('Ebene'))
            entry['Gruppe'] = _decode_numeric_field(entry.get('Gruppe'))

    with out_path.open('w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    return data


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Clean binary fields in PAUSCHALEN_Bedingungen")
    parser.add_argument('input', type=Path, help='Input JSON path')
    parser.add_argument('output', type=Path, help='Output JSON path')

    args = parser.parse_args()
    export_pauschalen_table(args.input, args.output)
