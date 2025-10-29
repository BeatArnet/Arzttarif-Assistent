"""
Utility script to normalise text-file encodings across the repository.

- Converts supported text files to UTF-8 (without BOM).
- Accepts existing UTF-8 data as-is.
- Falls back to Windows-1252 for bytes that are not valid UTF-8 so that
  umlauts and other locale-specific characters remain intact.

Run from the project root:

    python scripts/normalize_encoding.py
"""

from __future__ import annotations

import argparse
import codecs
from pathlib import Path
from typing import Iterable

# File suffixes that are treated as text and should be normalised.
TEXT_SUFFIXES: set[str] = {
    ".cfg",
    ".conf",
    ".css",
    ".csv",
    ".env",
    ".html",
    ".ini",
    ".js",
    ".json",
    ".md",
    ".ps1",
    ".py",
    ".rst",
    ".sh",
    ".ts",
    ".txt",
    ".yaml",
    ".yml",
}

# Individual filenames without suffixes that we still want to treat as text.
TEXT_BARE_FILENAMES: set[str] = {
    ".gitattributes",
    ".gitignore",
    "Procfile",
    "README",
}

# Binary file suffixes to skip explicitly.
BINARY_SUFFIXES: set[str] = {
    ".faiss",
    ".ico",
    ".png",
    ".svg",
}

# Common mojibake sequences (CP1252 interpreted as UTF-8) mapped back to Unicode.
MOJIBAKE_REPLACEMENTS: dict[str, str] = {
    "\u00c3\u201e": "Ä",
    "\u00c3\u0153": "Ü",
    "\u00e2\u20ac\u2018": "‘",
    "\u00e2\u20ac\u2019": "’",
    "\u00e2\u20ac\u201c": "“",
    "\u00e2\u20ac\u201d": "”",
    "\u00e2\u20ac\xa6": "…",
    "\u00e2\u20ac\xaf": "\u202f",  # schmaler geschützter Zwischenraum
}


def _cp1252_fallback(error):
    """Fallback handler for both decoding and encoding operations."""
    if isinstance(error, UnicodeDecodeError):
        byte = error.object[error.start : error.start + 1]
        return byte.decode("latin-1"), error.start + 1
    if isinstance(error, UnicodeEncodeError):
        char = error.object[error.start]
        return char.encode("utf-8"), error.start + 1
    raise error  # pragma: no cover - safety net


codecs.register_error("cp1252_fallback", _cp1252_fallback)
codecs.register_error("latin_fallback", _cp1252_fallback)


def _repair_mojibake(text: str) -> str:
    """Attempt to fix common UTF-8/CP1252 mojibake artefacts."""
    # Encode via latin-1 so every codepoint maps to the same byte.
    raw = text.encode("latin-1", errors="latin_fallback")
    repaired = raw.decode("utf-8", errors="latin_fallback")
    return repaired


def iter_target_files(root: Path) -> Iterable[Path]:
    exclude_dirs = {".git", "__pycache__", ".mypy_cache", ".pytest_cache"}
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if any(part in exclude_dirs for part in path.parts):
            continue
        suffix = path.suffix.lower()
        if suffix in BINARY_SUFFIXES:
            continue
        if suffix in TEXT_SUFFIXES or path.name in TEXT_BARE_FILENAMES or suffix == "":
            yield path


def normalise_file(path: Path, dry_run: bool = False) -> bool:
    data = path.read_bytes()
    if not data:
        return False
    # Skip likely binary files.
    if b"\x00" in data:
        return False

    changed = False
    # Remove UTF-8 BOM if present.
    if data.startswith(codecs.BOM_UTF8):
        data = data[len(codecs.BOM_UTF8) :]
        changed = True

    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        text = data.decode("utf-8", errors="cp1252_fallback")
        changed = True

    repaired = _repair_mojibake(text)
    if repaired != text:
        text = repaired
        changed = True

    for src, dst in MOJIBAKE_REPLACEMENTS.items():
        if src in text:
            text = text.replace(src, dst)
            changed = True

    encoded = text.encode("utf-8")
    if encoded != path.read_bytes():
        changed = True

    if changed and not dry_run:
        path.write_text(text, encoding="utf-8")
    return changed


def main() -> None:
    parser = argparse.ArgumentParser(description="Normalise repository text encodings to UTF-8.")
    parser.add_argument("--dry-run", action="store_true", help="Show files that would change.")
    parser.add_argument(
        "--root",
        type=Path,
        default=Path("."),
        help="Project root to process (defaults to current directory).",
    )
    args = parser.parse_args()

    changed_files: list[Path] = []
    for file_path in iter_target_files(args.root):
        if normalise_file(file_path, dry_run=args.dry_run):
            changed_files.append(file_path)

    if args.dry_run:
        if changed_files:
            print("Files requiring normalisation:")
            for path in changed_files:
                print(path)
        else:
            print("All checked files already use UTF-8 encoding.")
    else:
        if changed_files:
            print("Normalised encodings for:")
            for path in changed_files:
                print(path)
        else:
            print("No encoding changes were necessary.")


if __name__ == "__main__":
    main()
