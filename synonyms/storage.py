"""Persistence helpers for synonym catalogs."""

from __future__ import annotations

import json
from pathlib import Path

from .models import SynonymCatalog, SynonymEntry


def load_synonyms(path: str | Path) -> SynonymCatalog:
    """Return the catalog stored at ``path`` or an empty catalog if not found."""
    p = Path(path)
    catalog = SynonymCatalog()
    if p.exists():
        raw = p.read_bytes()
        def _decode() -> str:
            for enc in ("utf-8-sig", "utf-16"):
                try:
                    return raw.decode(enc)
                except UnicodeDecodeError:
                    continue
            return raw.decode("utf-8", errors="replace")

        text = _decode()
        if not text.strip():
            return catalog

        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            cleaned = "".join(ch for ch in text if ch >= " " or ch in "\n\t\r")
            if not cleaned.strip():
                return catalog
            data = json.loads(cleaned)
        for base, value in data.items():
            syns: list[str] = []
            by_lang: dict[str, list[str]] = {}
            lkn = None
            if isinstance(value, dict):
                # new format with language separation
                lkn = value.get("lkn") or value.get("LKN")
                if "synonyms" in value and isinstance(value["synonyms"], dict):
                    for lang, items in value["synonyms"].items():
                        variants = [str(s).strip() for s in items if isinstance(s, str)]
                        by_lang[lang] = variants
                        syns.extend(variants)
                else:
                    syns.extend(list(value.get("synonyms", [])))
                # backward compatibility for top-level language keys
                for lang in ("de", "fr", "it", "en"):  # common language codes
                    if lang in value:
                        variants = [str(s).strip() for s in value[lang] if isinstance(s, str)]
                        by_lang.setdefault(lang, []).extend(variants)
                        syns.extend(variants)
            else:
                syns.extend(list(value))
            entry = SynonymEntry(
                base_term=base,
                synonyms=syns,
                lkn=str(lkn) if lkn is not None else None,
                by_lang=by_lang,
            )
            catalog.entries[base] = entry
            # update reverse lookup index (case-insensitive)
            catalog.index[base.lower()] = base
            for syn in syns:
                key = syn.lower()
                catalog.index.setdefault(key, base)
    return catalog


def save_synonyms(catalog: SynonymCatalog, path: str | Path) -> None:
    """Persist ``catalog`` as JSON at ``path``."""
    p = Path(path)
    data: dict[str, object] = {}
    for base, entry in catalog.entries.items():
        obj: dict[str, object] = {}
        if entry.lkn is not None:
            obj["lkn"] = entry.lkn
        if entry.by_lang:
            obj["synonyms"] = {lang: syns for lang, syns in entry.by_lang.items() if syns}
        elif entry.synonyms:
            obj["synonyms"] = entry.synonyms
        data[base] = obj if obj else []
   
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def validate_catalog(catalog: SynonymCatalog) -> None:
    """Raise ``ValueError`` if the catalog contains malformed entries."""
    for base, entry in catalog.entries.items():
        if not isinstance(entry.base_term, str):
            raise ValueError(f"Invalid base term: {base}")
        if not isinstance(entry.synonyms, list):
            raise ValueError(f"Invalid synonyms for {base}")
        if entry.lkn is not None and not isinstance(entry.lkn, str):
            raise ValueError(f"Invalid LKN for {base}")
        if not isinstance(entry.by_lang, dict):
            raise ValueError(f"Invalid language mapping for {base}")
