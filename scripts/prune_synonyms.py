#!/usr/bin/env python3
"""Prune synonym lists according to editorial heuristics.

Rules:
* Remove synonyms that appear in more than FREQ_THRESHOLD distinct entries.
* Drop duplicates, title fragments and very short single tokens.
* Prefer multi-word phrases and keep at most MAX_SYNONYMS_PER_LANG items per language.
"""

from __future__ import annotations

import json
import re
import unicodedata
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Tuple

BASE_DIR = Path(__file__).resolve().parents[1]
DATA_PATH = BASE_DIR / "data" / "synonyms.json"

FREQ_THRESHOLD = 5  # remove synonyms that occur in more than this many entries
MAX_SYNONYMS_PER_LANG = 3
MIN_TOKEN_LENGTH = 4  # ignore very short single tokens (e.g. "op")

TOKEN_RE = re.compile(r"[0-9a-z\u00c0-\u017f]+", re.IGNORECASE)


@dataclass
class LanguageStats:
    removed: Counter
    before: int
    after: int


def normalize(text: str) -> str:
    """Return a casefolded, trimmed representation for comparisons."""
    return unicodedata.normalize("NFKC", text).casefold().strip()


def is_multiword(text: str) -> bool:
    stripped = text.strip()
    return any(ch in stripped for ch in (" ", "-", "/"))


def title_tokens(title: str) -> set[str]:
    norm_title = unicodedata.normalize("NFKC", title).casefold()
    return {match.group(0) for match in TOKEN_RE.finditer(norm_title)}


def collect_languages(data: Dict[str, dict]) -> List[str]:
    langs = set()
    for entry in data.values():
        langs.update(entry.get("synonyms", {}).keys())
    return sorted(langs)


def collect_frequencies(data: Dict[str, dict], languages: Iterable[str]) -> Dict[str, Counter]:
    """Count in how many entries each synonym occurs (per language)."""
    freq: Dict[str, Counter] = {lang: Counter() for lang in languages}
    for entry in data.values():
        syns = entry.get("synonyms", {})
        for lang in languages:
            seen_in_entry = set()
            for raw in syns.get(lang, []):
                norm = normalize(raw)
                if not norm or norm in seen_in_entry:
                    continue
                freq[lang][norm] += 1
                seen_in_entry.add(norm)
    return freq


def prune_entry(
    title: str,
    entry: dict,
    languages: Iterable[str],
    freq: Dict[str, Counter],
    stats: Dict[str, LanguageStats],
) -> None:
    norm_title = normalize(title)
    tokens = title_tokens(title)
    synonyms = entry.get("synonyms", {})

    for lang in languages:
        lang_syns = synonyms.get(lang, []) or []
        lang_stat = stats[lang]
        lang_stat.before += len(lang_syns)

        unique: List[Tuple[str, str]] = []
        seen_norms = set()
        for raw in lang_syns:
            norm = normalize(raw)
            if not norm:
                lang_stat.removed["empty"] += 1
                continue
            if norm in seen_norms:
                lang_stat.removed["duplicate"] += 1
                continue
            seen_norms.add(norm)
            unique.append((raw, norm))

        filtered: List[Tuple[str, str]] = []
        freq_removed: List[Tuple[str, str]] = []
        for raw, norm in unique:
            syn_token_set = {match.group(0) for match in TOKEN_RE.finditer(norm)}
            if norm == norm_title:
                lang_stat.removed["identical_title"] += 1
                continue
            if not is_multiword(raw) and norm in tokens:
                lang_stat.removed["title_fragment"] += 1
                continue
            if syn_token_set and syn_token_set.issubset(tokens):
                lang_stat.removed["title_fragment_multi"] += 1
                continue
            if not is_multiword(raw) and len(norm) < MIN_TOKEN_LENGTH:
                lang_stat.removed["too_short"] += 1
                continue
            if freq[lang].get(norm, 0) > FREQ_THRESHOLD:
                lang_stat.removed["global_freq"] += 1
                freq_removed.append((raw, norm))
                continue
            filtered.append((raw, norm))

        if not filtered and freq_removed:
            filtered = freq_removed

        multiword = [raw for raw, _norm in filtered if is_multiword(raw)]
        long_single = [
            raw for raw, norm in filtered if not is_multiword(raw) and len(norm) >= 8
        ]
        prioritized = multiword + long_single

        if not prioritized and filtered:
            prioritized = [raw for raw, _norm in filtered]

        pruned_list = prioritized[:MAX_SYNONYMS_PER_LANG]
        lang_stat.after += len(pruned_list)
        synonyms[lang] = pruned_list

    entry["synonyms"] = synonyms


def prune_catalog(data: Dict[str, dict]) -> Tuple[Dict[str, dict], Dict[str, LanguageStats]]:
    languages = collect_languages(data)
    freq = collect_frequencies(data, languages)
    stats: Dict[str, LanguageStats] = {
        lang: LanguageStats(removed=Counter(), before=0, after=0) for lang in languages
    }

    for title, entry in data.items():
        prune_entry(title, entry, languages, freq, stats)

    return data, stats


def load_catalog(path: Path) -> Dict[str, dict]:
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def save_catalog(path: Path, data: Dict[str, dict]) -> None:
    formatted = json.dumps(data, ensure_ascii=False, indent=2)
    path.write_text(formatted + "\n", encoding="utf-8")


def format_stats(stats: Dict[str, LanguageStats]) -> str:
    lines = []
    for lang, lang_stat in sorted(stats.items()):
        total_removed = sum(lang_stat.removed.values())
        lines.append(
            f"{lang}: {lang_stat.before} -> {lang_stat.after} (removed {total_removed})"
        )
        for reason, count in lang_stat.removed.most_common():
            lines.append(f"  - {reason}: {count}")
    return "\n".join(lines)


def main() -> None:
    data = load_catalog(DATA_PATH)
    original_total = sum(
        len(syn)
        for entry in data.values()
        for syn in entry.get("synonyms", {}).values()
    )

    pruned_data, stats = prune_catalog(data)
    pruned_total = sum(
        len(syn)
        for entry in pruned_data.values()
        for syn in entry.get("synonyms", {}).values()
    )

    save_catalog(DATA_PATH, pruned_data)

    print(f"Synonyms total: {original_total} -> {pruned_total}")
    print(format_stats(stats))


if __name__ == "__main__":
    main()
