"""Storage helpers for synonym catalogues.

The persistence layer tolerates different JSON encodings and schema variants
that emerged during tool development. Loading normalises multilingual blocks
and rebuilds reverse indexes; saving emits the current format used by the GUI
and backend.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Dict, Iterable, List

from .models import SynonymCatalog, SynonymEntry

logger = logging.getLogger(__name__)

_CODE_SPLIT_RE = re.compile(r"[|,;\s]+")


def _normalize_code(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        text = value
    else:
        text = str(value)
    return text.strip().upper()


def _dedupe_preserve_order(items: Iterable[str]) -> List[str]:
    seen: set[str] = set()
    result: List[str] = []
    for item in items:
        if not item:
            continue
        if item not in seen:
            seen.add(item)
            result.append(item)
    return result


def _append_index_entry(target: Dict[str, List[str]], key: str, base: str) -> None:
    if not key:
        return
    bucket = target.setdefault(key, [])
    if base not in bucket:
        bucket.append(base)


def _add_index(target: Dict[str, List[str]], key: str, base: str) -> None:
    norm = " ".join(str(key).lower().split())
    if not norm:
        return

    _append_index_entry(target, norm, base)

    simplified = re.sub(r"[^a-z0-9]+", " ", norm).strip()
    if simplified and simplified != norm:
        _append_index_entry(target, simplified, base)

    if simplified:
        for token in simplified.split():
            if len(token) >= 4:
                _append_index_entry(target, token, base)


def _add_lkn_index(target: Dict[str, List[str]], code: str, base: str) -> None:
    norm = _normalize_code(code)
    if not norm:
        return
    bucket = target.setdefault(norm, [])
    if base not in bucket:
        bucket.append(base)


def _extend_codes(container: List[str], raw: object) -> None:
    if raw is None:
        return
    if isinstance(raw, (list, tuple, set)):
        for item in raw:
            _extend_codes(container, item)
        return
    if isinstance(raw, str):
        parts = [part for part in _CODE_SPLIT_RE.split(raw) if part]
    else:
        parts = [str(raw)]
    for part in parts:
        code = _normalize_code(part)
        if code:
            container.append(code)


def load_synonyms(path: str | Path) -> SynonymCatalog:
    """Return the catalog stored at ``path`` or an empty catalog if not found."""
    p = Path(path)
    catalog = SynonymCatalog()
    if not p.exists():
        logger.warning(
            "Synonymkatalog %s nicht gefunden \u2013 Erweiterungen deaktiviert", p
        )
        return catalog
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

    if not isinstance(data, dict):
        logger.error("Unerwartetes Synonymkatalog-Format: %s", type(data).__name__)
        return catalog

    for base, value in data.items():
        syns: List[str] = []
        by_lang: Dict[str, List[str]] = {}
        components: Dict[str, Dict[str, List[str]]] = {}
        lkns: List[str] = []
        comp_val = None

        if isinstance(value, dict):
            _extend_codes(lkns, value.get("lkns"))
            _extend_codes(lkns, value.get("lkn") or value.get("LKN"))

            syn_val = value.get("synonyms")
            if isinstance(syn_val, dict):
                for lang, items in syn_val.items():
                    if isinstance(items, dict):
                        inner: Dict[str, List[str]] = {}
                        lang_syns: List[str] = []
                        for comp, syn_list in items.items():
                            if isinstance(comp, str) and isinstance(syn_list, list):
                                cleaned = [
                                    str(s).strip()
                                    for s in syn_list
                                    if isinstance(s, str) and s.strip()
                                ]
                                if cleaned:
                                    deduped = _dedupe_preserve_order(cleaned)
                                    inner[comp] = deduped
                                    lang_syns.extend(deduped)
                        if inner:
                            components[lang] = inner
                            by_lang[lang] = _dedupe_preserve_order(lang_syns)
                            syns.extend(by_lang[lang])
                    elif isinstance(items, list):
                        variants = [
                            str(s).strip()
                            for s in items
                            if isinstance(s, str) and s.strip()
                        ]
                        if variants:
                            deduped = _dedupe_preserve_order(variants)
                            by_lang[lang] = deduped
                            syns.extend(deduped)
            elif isinstance(syn_val, list):
                syns.extend(
                    str(s).strip() for s in syn_val if isinstance(s, str) and s.strip()
                )
            elif syn_val:
                syns.append(str(syn_val).strip())

            for lang in ("de", "fr", "it", "en"):
                items = value.get(lang)
                if isinstance(items, list):
                    variants = [
                        str(s).strip()
                        for s in items
                        if isinstance(s, str) and s.strip()
                    ]
                    if variants:
                        current = by_lang.setdefault(lang, [])
                        for variant in variants:
                            if variant not in current:
                                current.append(variant)
                        syns.extend(variants)

            comp_val = value.get("components")

        elif isinstance(value, list):
            syns.extend(
                str(s).strip() for s in value if isinstance(s, str) and s.strip()
            )
        elif value is not None:
            text_value = str(value).strip()
            if text_value:
                syns.append(text_value)

        if isinstance(comp_val, dict):
            for lang, mapping in comp_val.items():
                if not isinstance(mapping, dict):
                    continue
                lang_components: Dict[str, List[str]] = {}
                lang_syns: List[str] = []
                for comp, syn_list in mapping.items():
                    if isinstance(comp, str) and isinstance(syn_list, list):
                        cleaned = [
                            str(s).strip()
                            for s in syn_list
                            if isinstance(s, str) and s.strip()
                        ]
                        if cleaned:
                            deduped = _dedupe_preserve_order(cleaned)
                            lang_components[comp] = deduped
                            lang_syns.extend(deduped)
                if lang_components:
                    components.setdefault(lang, {}).update(lang_components)
                    current = by_lang.setdefault(lang, [])
                    for variant in lang_syns:
                        if variant not in current:
                            current.append(variant)
                    syns.extend(lang_syns)

        entry = SynonymEntry(
            base_term=str(base),
            synonyms=_dedupe_preserve_order(syns),
            lkns=_dedupe_preserve_order(lkns),
            by_lang={lang: _dedupe_preserve_order(vals) for lang, vals in by_lang.items()},
            components=components,
        )

        catalog.entries[entry.base_term] = entry

    rebuild_indexes(catalog)
    return catalog


def save_synonyms(catalog: SynonymCatalog, path: str | Path) -> None:
    """Persist ``catalog`` as JSON at ``path``."""
    p = Path(path)
    data: dict[str, object] = {}
    for base, entry in catalog.entries.items():
        obj: dict[str, object] = {}
        if entry.lkns:
            obj["lkns"] = entry.lkns
            if len(entry.lkns) == 1:
                obj["lkn"] = entry.lkns[0]
        if entry.components:
            obj["synonyms"] = {
                lang: {comp: syns[:] for comp, syns in mapping.items() if syns}
                for lang, mapping in entry.components.items()
                if mapping
            }
        elif entry.by_lang:
            obj["synonyms"] = {
                lang: syns[:] for lang, syns in entry.by_lang.items() if syns
            }
        elif entry.synonyms:
            obj["synonyms"] = entry.synonyms[:]
        if entry.components:
            obj["components"] = {
                lang: {comp: syns[:] for comp, syns in mapping.items() if syns}
                for lang, mapping in entry.components.items()
                if mapping
            }
        data[base] = obj if obj else []

    p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def compare_catalogues(old: SynonymCatalog, new: SynonymCatalog) -> Dict[str, str]:
    """Return status mapping when ``new`` is compared against ``old``.

    The returned dictionary maps each base term to one of the following
    strings:

    ``"added"``     -- present only in ``new``.
    ``"removed"``   -- present only in ``old``.
    ``"changed"``   -- exists in both but differs in LKN or synonyms.
    ``"unchanged"`` -- identical entries.
    """

    statuses: Dict[str, str] = {}
    old_keys = set(old.entries.keys())
    new_keys = set(new.entries.keys())
    for key in old_keys | new_keys:
        if key not in old_keys:
            statuses[key] = "added"
        elif key not in new_keys:
            statuses[key] = "removed"
        else:
            old_entry = old.entries[key]
            new_entry = new.entries[key]
            if (
                set(old_entry.lkns) != set(new_entry.lkns)
                or set(old_entry.synonyms) != set(new_entry.synonyms)
            ):
                statuses[key] = "changed"
            else:
                statuses[key] = "unchanged"
    return statuses


def validate_catalog(catalog: SynonymCatalog) -> None:
    """Raise ``ValueError`` if the catalog contains malformed entries."""
    for base, entry in catalog.entries.items():
        if not isinstance(entry.base_term, str):
            raise ValueError(f"Invalid base term: {base}")
        if not isinstance(entry.synonyms, list):
            raise ValueError(f"Invalid synonyms for {base}")
        if not isinstance(entry.lkns, list):
            raise ValueError(f"Invalid LKN list for {base}")
        for code in entry.lkns:
            if not isinstance(code, str):
                raise ValueError(f"Invalid LKN value for {base}: {code!r}")
        if not isinstance(entry.by_lang, dict):
            raise ValueError(f"Invalid language mapping for {base}")
        if not isinstance(entry.components, dict):
            raise ValueError(f"Invalid components for {base}")


def rebuild_indexes(catalog: SynonymCatalog) -> None:
    """Rebuild synonym and LKN reverse indexes for ``catalog``."""
    catalog.index.clear()
    catalog.lkn_index.clear()

    for base, entry in catalog.entries.items():
        _add_index(catalog.index, base, base)
        for syn in entry.synonyms:
            _add_index(catalog.index, syn, base)
        for lang_values in entry.by_lang.values():
            for syn in lang_values:
                _add_index(catalog.index, syn, base)
        for mapping in entry.components.values():
            for syn_list in mapping.values():
                for syn in syn_list:
                    _add_index(catalog.index, syn, base)
        for code in entry.lkns:
            _add_lkn_index(catalog.lkn_index, code, base)

