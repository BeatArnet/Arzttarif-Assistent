import argparse
import json
from pathlib import Path

from typing import Dict, Iterable, List, Mapping

try:
    # utils.py lives at repo root and contains the SYNONYM_MAP constant
    from utils import SYNONYM_MAP  # type: ignore
except Exception:  # pragma: no cover - optional import
    SYNONYM_MAP: Dict[str, List[str]] = {}

def _convert_mapping(mapping: Mapping[str, Iterable[str]]) -> List[dict]:
    """Return the new schema for ``mapping``."""
    new_entries = []
    for idx, (base, synonyms) in enumerate(sorted(mapping.items()), 1):
        entry = {
            "concept_id": f"syn{idx:04d}",
            "canonical_terms": [base],
            "synonyms": list(synonyms),
            "status": "approved",
        }
        new_entries.append(entry)
    return new_entries


def migrate(input_path: Path | None, output_path: Path, from_utils: bool = False) -> None:
    """Convert synonym mappings into the new catalog structure."""
    mapping: Dict[str, List[str]] = {}
    if from_utils or not input_path:
        mapping = SYNONYM_MAP
    else:
        data = json.loads(input_path.read_text(encoding="utf-8"))
        mapping = {str(k): v for k, v in data.items()}

    new_entries = _convert_mapping(mapping)

    output_path.write_text(json.dumps(new_entries, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Migrate synonyms.json to new schema")
    parser.add_argument("output", type=Path, help="path for new synonyms.json")
    parser.add_argument("input", type=Path, nargs="?", default=None, help="optional path to old synonyms.json")
    parser.add_argument("--from-utils", action="store_true", help="use SYNONYM_MAP from utils.py instead of a file")
    args = parser.parse_args()
    migrate(args.input, args.output, from_utils=args.from_utils)

if __name__ == "__main__":
    main()
